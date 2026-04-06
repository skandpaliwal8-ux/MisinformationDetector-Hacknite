"""
Fact-Check Agent
----------------
Uses Tavily to search fact-check sites directly.
"""
import config
from agents.state import AgentSignal, PipelineState


def fact_check_agent(state: PipelineState) -> PipelineState:
    claims: list[str] = state.get("_extracted_claims") or []

    if not claims:
        if state.get("input_type") == "text_claim":
            claims = [state["raw_input"][:200]]
        else:
            state["fact_check_signal"] = AgentSignal(
                score=0.0, confidence=0.0,
                details="No claims to fact-check.",
                sources=[],
            )
            return state

    all_verdicts = []
    all_sources  = []
    fake_count   = 0

    for claim in claims[:3]:
        results = _check_claim(claim)
        for r in results:
            verdict_text = r.get("textualRating", "").lower()
            publisher    = r.get("claimReview", [{}])[0].get("publisher", {}).get("name", "Unknown")
            review_url   = r.get("claimReview", [{}])[0].get("url", "")

            all_verdicts.append(f"{publisher}: '{r.get('text', claim)[:80]}' → {verdict_text}")
            all_sources.append(review_url)

            if any(w in verdict_text for w in ("false", "fake", "mislead", "debunked", "no evidence")):
                fake_count += 1

    if not all_verdicts:
        state["fact_check_signal"] = AgentSignal(
            score=0.0, confidence=0.30,
            details="No fact-check records found for these claims.",
            sources=[],
        )
        return state

    score = min(fake_count / max(len(all_verdicts), 1), 1.0)
    state["fact_check_signal"] = AgentSignal(
        score=score,
        confidence=0.85,
        details=(
            f"Found {len(all_verdicts)} fact-check record(s). "
            f"{fake_count} flagged as false/misleading.\n"
            + "\n".join(f"  • {v}" for v in all_verdicts[:5])
        ),
        sources=list(filter(None, all_sources))[:5],
    )

    if fake_count > 0:
        existing = state.get("red_flags") or []
        state["red_flags"] = existing + [
            f"{fake_count} claim(s) previously debunked by fact-checkers"
        ]

    return state


def _check_claim(query: str) -> list[dict]:
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=config.TAVILY_API_KEY)

        response = client.search(
            query=f"fact check {query} snopes politifact reuters",
            max_results=5,
            search_depth="advanced",
            include_domains=[
                "snopes.com",
                "politifact.com",
                "reuters.com",
                "apnews.com",
                "factcheck.org",
                "fullfact.org",
                "bbc.com",
            ],
        )

        claims = []
        for r in response.get("results", []):
            content = r.get("content", "").lower()

            if any(w in content for w in ("false", "fake", "misleading", "debunked", "no evidence")):
                rating = "false"
            elif any(w in content for w in ("true", "correct", "accurate", "confirmed")):
                rating = "true"
            else:
                rating = "unverified"

            claims.append({
                "text": query,
                "textualRating": rating,
                "claimReview": [{
                    "publisher": {"name": r.get("title", "Unknown")[:40]},
                    "url": r.get("url", ""),
                }],
            })
        return claims

    except Exception:
        return []