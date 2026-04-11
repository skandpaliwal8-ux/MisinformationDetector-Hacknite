"""
Fact-Check Agent
----------------
Uses SearXNG to search fact-check sites directly.
"""
import httpx
import config
from agents.state import AgentSignal, PipelineState


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

def _check_claim(query: str) -> list[dict]:
    results = _search(
        f"fact check {query} snopes politifact reuters",
        max_results=5,
    )

    claims = []
    for r in results:
        content = r.get("body", "").lower()

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
                "url":       r.get("href", ""),
            }],
        })
    return claims

def fact_check_agent(state: PipelineState) -> PipelineState:
    claims: list[str] = state.get("extracted_claims") or []

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
    score        = 0.0    # ADD THIS LINE

    for claim in claims[:3]:
        results = _check_claim(claim)
        for r in results:
            verdict_text = r.get("textualRating", "").lower()
            publisher    = r.get("claimReview", [{}])[0].get("publisher", {}).get("name", "Unknown")
            review_url   = r.get("claimReview", [{}])[0].get("url", "")

            all_verdicts.append(
                f"{publisher}: '{r.get('text', claim)[:80]}' → {verdict_text}"
                + (f" | Source: {review_url}" if review_url else "")
            )
            if review_url:
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


