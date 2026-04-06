"""
Claim Verifier Agent
--------------------
For each extracted claim, searches DuckDuckGo to find
contradicting or supporting evidence from reliable sources.
Uses Groq to reason about whether the evidence supports or contradicts the claim.
"""
from duckduckgo_search import DDGS
from groq import Groq
import config
from agents.state import AgentSignal, PipelineState

_client = Groq(api_key=config.GROQ_API_KEY)

VERIFY_PROMPT = """You are a strict fact-checker working for a reputable news organization.
A claim has been made. Search results have been gathered from the web.
Your job is to deliver a clear verdict — do NOT say inconclusive unless there is genuinely zero relevant evidence.

Claim: {claim}

Search results:
{results}

Rules:
- If multiple credible sources (BBC, Reuters, WHO, CDC, Wikipedia, major universities) contradict the claim → CONTRADICTED
- If the claim matches what credible sources say → SUPPORTED  
- If search results are completely irrelevant with zero information about the claim → INCONCLUSIVE
- Conspiracy theories and debunked misinformation should be marked CONTRADICTED if credible sources deny them
- Do NOT be neutral to be safe — make a call based on the evidence

Respond in this EXACT format:
VERDICT: <SUPPORTED | CONTRADICTED | INCONCLUSIVE>
CONFIDENCE: <0.0 to 1.0>
REASONING: <one sentence citing a specific source from the results>
"""

def claim_verifier_agent(state: PipelineState) -> PipelineState:
    claims = state.get("_extracted_claims", [])

    if not claims:
        state["_verification_results"] = []
        return state

    verification_results = []
    contradiction_count = 0

    for claim in claims[:3]:
        result = _verify_single_claim(claim)
        verification_results.append(result)
        if result["verdict"] == "CONTRADICTED":
            contradiction_count += 1

    state["_verification_results"] = verification_results

    if not verification_results:
        return state

    # Score based on how many claims were contradicted
    # Replace the scoring section with this
    total = len(verification_results)
    contradiction_count = sum(1 for r in verification_results if r["verdict"] == "CONTRADICTED")
    inconclusive_count  = sum(1 for r in verification_results if r["verdict"] == "INCONCLUSIVE")
    supported_count     = sum(1 for r in verification_results if r["verdict"] == "SUPPORTED")

    # Harsher scoring — one contradiction is enough to be suspicious
    if contradiction_count >= 2:
        score = 0.90
    elif contradiction_count == 1:
        score = 0.65
    elif inconclusive_count == total:
        score = 0.30   # all inconclusive = uncertain, not real
    else:
        score = 0.10   # all supported = likely real

    details = f"Verified {len(verification_results)} claims. {contradiction_count} contradicted by web evidence.\n"
    details += "\n".join(
        f"  • [{r['verdict']}] {r['claim'][:60]} — {r['reasoning']}"
        for r in verification_results
    )

    # Store as a signal the synthesis agent can use
 # Change _claim_verify_signal to claim_verify_signal everywhere
    state["claim_verify_signal"] = AgentSignal(
        score=score,
        confidence=0.75,
        details=details,
        sources=[r["source"] for r in verification_results if r.get("source")],
    )
    
    if contradiction_count > 0:
        existing = state.get("red_flags") or []
        new_flags = [
            f"Claim contradicted by web sources: '{r['claim'][:60]}'"
            for r in verification_results
            if r["verdict"] == "CONTRADICTED"
        ]
        state["red_flags"] = existing + new_flags

    return state


def _verify_single_claim(claim: str) -> dict:
    search_results = []
    all_urls = []

    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=config.TAVILY_API_KEY)

        # Three targeted searches
        for query in [
            claim,
            f"fact check {claim}",
            f"is it true that {claim}",
        ]:
            try:
                response = client.search(
                    query=query,
                    max_results=3,
                    search_depth="advanced",
                )
                for r in response.get("results", []):
                    search_results.append(
                        f"Source: {r.get('url', '')}\n"
                        f"Title: {r.get('title', '')}\n"
                        f"Content: {r.get('content', '')[:250]}"
                    )
                    all_urls.append(r.get("url", ""))
            except Exception:
                continue

    except ImportError:
        return {
            "claim": claim,
            "verdict": "INCONCLUSIVE",
            "confidence": 0.0,
            "reasoning": "tavily-python not installed.",
            "source": "",
        }
    except Exception as e:
        return {
            "claim": claim,
            "verdict": "INCONCLUSIVE",
            "confidence": 0.0,
            "reasoning": f"Search failed: {e}",
            "source": "",
        }

    if not search_results:
        return {
            "claim": claim,
            "verdict": "INCONCLUSIVE",
            "confidence": 0.0,
            "reasoning": "No search results found.",
            "source": "",
        }

    try:
        resp = _client.chat.completions.create(
            model=config.GROQ_TEXT_MODEL,
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": VERIFY_PROMPT.format(
                    claim=claim,
                    results="\n\n".join(search_results[:6]),
                ),
            }],
        )
        raw = resp.choices[0].message.content or ""
        lines = {
            line.split(":")[0].strip(): ":".join(line.split(":")[1:]).strip()
            for line in raw.splitlines() if ":" in line
        }

        return {
            "claim":      claim,
            "verdict":    lines.get("VERDICT", "INCONCLUSIVE"),
            "confidence": _safe_float(lines.get("CONFIDENCE", "0.5")),
            "reasoning":  lines.get("REASONING", ""),
            "source":     all_urls[0] if all_urls else "",
        }
    except Exception as e:
        return {
            "claim": claim,
            "verdict": "INCONCLUSIVE",
            "confidence": 0.0,
            "reasoning": f"Groq reasoning failed: {e}",
            "source": "",
        }

def _safe_float(val: str) -> float:
    try:
        return max(0.0, min(1.0, float(val)))
    except (ValueError, TypeError):
        return 0.0