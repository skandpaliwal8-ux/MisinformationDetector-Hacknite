"""
Reverse Search Agent
--------------------
Uses DuckDuckGo search (no API key, no server needed) to find
where this content has appeared online before.
"""
from duckduckgo_search import DDGS
from agents.state import AgentSignal, PipelineState


def reverse_search_agent(state: PipelineState) -> PipelineState:
    raw = state.get("raw_input", "")
    input_type = state.get("input_type", "")

    if not raw:
        state["reverse_search_signal"] = _no_result("No input provided.")
        return state

    try:
        with DDGS() as ddgs:
            if input_type == "image_url":
                # Search for the image URL directly to find where it appeared
                results = list(ddgs.text(raw, max_results=10))
            elif input_type == "article_url":
                results = list(ddgs.text(f'"{raw}"', max_results=10))
            else:
                # Text claim — search for it directly
                results = list(ddgs.text(raw[:200], max_results=10))

    except Exception as e:
        state["reverse_search_signal"] = AgentSignal(
            score=0.0, confidence=0.2,
            details=f"Reverse search failed: {e}",
            sources=[],
        )
        state["timeline"] = []
        return state

    if not results:
        state["reverse_search_signal"] = AgentSignal(
            score=0.0, confidence=0.30,
            details="No results found in reverse search. Could not verify origin.",
            sources=[],
        )
        state["timeline"] = []
        return state

    timeline, score, details, red_flags = _analyse_results(results, raw)

    state["reverse_search_signal"] = AgentSignal(
        score=score,
        confidence=0.65,
        details=details,
        sources=[r.get("href", "") for r in results[:3]],
    )
    state["timeline"] = timeline

    existing = state.get("red_flags") or []
    state["red_flags"] = existing + red_flags
    return state


def _analyse_results(results: list[dict], original_input: str):
    timeline = []
    red_flags = []

    for r in results[:10]:
        entry = {
            "title": r.get("title", "Unknown"),
            "url":   r.get("href", ""),
            "date":  r.get("published", "Unknown"),
            "body":  r.get("body", "")[:100],
        }
        timeline.append(entry)

    score = 0.0
    details = f"Found {len(results)} appearances of this content online."

    # Check if the original source matches the earliest result
    if results:
        first_result_url = results[0].get("href", "")
        if original_input not in first_result_url and first_result_url:
            score += 0.2
            details += f" First search result points to a different source: {first_result_url}."
            red_flags.append(f"Content found at different source: {first_result_url}")

    # If many results found, content is widely spread
    if len(results) >= 8:
        details += f" Content appears widely across {len(results)} sources."

    return timeline, min(score, 1.0), details, red_flags


def _no_result(msg: str) -> AgentSignal:
    return AgentSignal(score=0.0, confidence=0.0, details=msg, sources=[])
