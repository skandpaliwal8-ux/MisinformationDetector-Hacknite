"""
Reverse Search Agent
--------------------
Searches SearXNG for the image/article URL to find the original source,
first publication date, and whether it has appeared in a different context.
"""
import httpx
from datetime import datetime
from agents.state import AgentSignal, PipelineState
import config


"""
Reverse Search Agent
--------------------
Uses DuckDuckGo search (no API key, no server needed) to find
where this content has appeared online before.
"""
from duckduckgo_search import DDGS
from datetime import datetime
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

# ── SearXNG helpers ───────────────────────────────────────────────────────────

def _image_search(image_url: str) -> list[dict]:
    """Use SearXNG's images engine to find where this image appeared."""
    try:
        with httpx.Client(timeout=15) as client:
            r = client.get(
                f"{config.SEARXNG_BASE_URL}/search",
                params={
                    "q": image_url,
                    "engines": "google images,bing images",
                    "format": "json",
                    "safesearch": "0",
                },
            )
            r.raise_for_status()
            return r.json().get("results", [])
    except Exception:
        return []


def _text_search(query: str) -> list[dict]:
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=config.TAVILY_API_KEY)
        response = client.search(query=query, max_results=10)
        return [
            {
                "title": r.get("title", ""),
                "href":  r.get("url", ""),
                "body":  r.get("content", "")[:150],
            }
            for r in response.get("results", [])
        ]
    except Exception:
        return []

# ── Analysis ──────────────────────────────────────────────────────────────────

def _analyse_results(results: list[dict], original_input: str):
    timeline = []
    red_flags = []

    for r in results[:10]:
        entry = {
            "title":    r.get("title", "Unknown"),
            "url":      r.get("url", ""),
            "date":     r.get("publishedDate", "Unknown"),
            "engine":   r.get("engine", ""),
        }
        timeline.append(entry)

    # Find the earliest dated result
    dated = [
        r for r in timeline
        if r["date"] != "Unknown"
    ]

    score = 0.0
    details = f"Found {len(results)} appearances of this content online."

    if dated:
        try:
            earliest = min(dated, key=lambda x: _parse_date(x["date"]))
            details += f" Earliest known appearance: {earliest['date']} at {earliest['url']}."

            # If earliest source is different from the claim's source — red flag
            if original_input not in earliest["url"]:
                score += 0.3
                red_flags.append(
                    f"Content first appeared at a different source: {earliest['url']}"
                )
        except Exception:
            pass

    if len(results) > 20:
        details += f" Content has been shared widely ({len(results)}+ sources)."

    return timeline, min(score, 1.0), details, red_flags


def _parse_date(date_str: str) -> datetime:
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%B %d, %Y"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return datetime.max


def _no_result(msg: str) -> AgentSignal:
    return AgentSignal(score=0.0, confidence=0.0, details=msg, sources=[])