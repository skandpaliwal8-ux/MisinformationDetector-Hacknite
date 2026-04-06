import requests
import config
from agents.state import AgentSignal, PipelineState

def ai_text_agent(state: PipelineState) -> PipelineState:
    text = state.get("article_text")
    if not text or len(text.strip()) < 50:
        state["ai_text_signal"] = AgentSignal(
            score=0.0, confidence=0.0,
            details="Insufficient text.",
            sources=[],
        )
        return state

    try:
        response = requests.post(
            SAPLING_API_URL,
            json={"key": SAPLING_API_KEY, "text": text[:3000]},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        score = float(data.get("score", 0.0))  # 0 = human, 1 = AI

        state["ai_text_signal"] = AgentSignal(
            score=score,
            confidence=0.80,
            details=f"Sapling AI detection score: {score:.0%}. "
                    + ("⚠ Likely AI-written." if score > 0.6 else "✓ Likely human-written."),
            sources=["sapling.ai"],
        )
    except Exception as e:
        state["ai_text_signal"] = AgentSignal(
            score=0.0, confidence=0.0,
            details=f"Sapling detection failed: {e}",
            sources=[],
        )

    return state