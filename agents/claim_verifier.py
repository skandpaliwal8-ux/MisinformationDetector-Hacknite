"""
Claim Verifier Agent
--------------------
For each extracted claim, searches SearXNG to find
contradicting or supporting evidence from reliable sources.
Uses Groq to reason about whether the evidence supports or contradicts the claim.
"""
import httpx                          # ← ADDED
import config
from groq import Groq
from agents.state import AgentSignal, PipelineState

_client = Groq(api_key=config.GROQ_API_KEY)


def _search(query: str, max_results: int = 5) -> list[dict]:
    try:
        with httpx.Client(timeout=15) as client:
            r = client.get(
                "http://localhost:8080/search",
                params={
                    "q":          query,
                    "format":     "json",
                    "safesearch": "0",
                    "time_range": "month",    # ADD THIS
                },
                headers={"X-Forwarded-For": "127.0.0.1"},
            )
            r.raise_for_status()
            results = r.json().get("results", [])
            return [
                {
                    "title": res.get("title", ""),
                    "href":  res.get("url", res.get("href", "")),
                    "body":  res.get("content", res.get("snippet", ""))[:250],
                }
                for res in results[:max_results]
            ]
    except Exception as e:
        return []


def _verify_single_claim(claim: str) -> dict:
    search_results = []
    all_urls = []

    for query in [claim, f"fact check {claim}", f"is it true that {claim}"]:
        results = _search(query, max_results=3)
        for r in results:
            search_results.append(
                f"Source: {r['href']}\nTitle: {r['title']}\n{r['body']}"
            )
            all_urls.append(r["href"])

    if not search_results:
        return {
            "claim":      claim,
            "verdict":    "INCONCLUSIVE",
            "confidence": 0.0,
            "reasoning":  "No search results found.",
            "source":     "",
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
            "claim":      claim,
            "verdict":    "INCONCLUSIVE",
            "confidence": 0.0,
            "reasoning":  f"Groq reasoning failed: {e}",
            "source":     "",
        }

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

    if not verification_results:
        state["claim_verify_signal"] = AgentSignal(
            score=0.3,
            confidence=0.40,
            details="All claims were inconclusive — no search results returned.",
            sources=[],
        )
        return state

    state["claim_verify_signal"] = AgentSignal(
        score=score,
        confidence=0.75,
        details=details,
        sources=[r["source"] for r in verification_results if r.get("source")],
    )

    return state

def _safe_float(val: str) -> float:
    try:
        return max(0.0, min(1.0, float(val)))
    except (ValueError, TypeError):
        return 0.0