import config
from groq import Groq
from agents.state import AgentSignal, PipelineState

_client = Groq(api_key=config.GROQ_API_KEY)

AI_TEXT_PROMPT = """You are an expert at detecting AI-generated text.
Analyze the following text and determine if it was written by an AI or a human.

Look for these AI writing signals:
- Unnaturally uniform sentence length and structure
- Overly formal or generic phrasing
- Lack of personal voice, opinion, or stylistic quirks
- Repetitive transition words (furthermore, moreover, additionally)
- Perfect grammar with no natural human errors
- Suspiciously balanced arguments covering all sides equally

Text to analyze:
{text}

Respond in this EXACT format:
AI_SCORE: <0.0 to 1.0>
CONFIDENCE: <0.0 to 1.0>
REASONING: <one paragraph under 60 words>
SIGNALS: <comma separated list of AI signals found, or NONE>
"""


def ai_text_agent(state: PipelineState) -> PipelineState:
    text = state.get("article_text")

    if not text or len(text.strip()) < 50:
        state["ai_text_signal"] = AgentSignal(
            score=0.0, confidence=0.0,
            details="Insufficient text for AI detection analysis.",
            sources=[],
        )
        return state

    try:
        resp = _client.chat.completions.create(
            model=config.GROQ_TEXT_MODEL,
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": AI_TEXT_PROMPT.format(text=text[:3000]),
            }],
        )

        raw = resp.choices[0].message.content or ""
        score, confidence, reasoning, signals = _parse_response(raw)

        state["ai_text_signal"] = AgentSignal(
            score=score,
            confidence=confidence,
            details=(
                f"AI text probability: {score:.0%}. {reasoning} "
                "⚠ LLM-based detection — treat as one signal among many."
            ),
            sources=[f"groq/{config.GROQ_TEXT_MODEL}"],
        )

        if score > 0.6:
            existing = state.get("red_flags") or []
            state["red_flags"] = existing + [
                f"Possible AI-written text detected: {', '.join(signals[:3])}"
            ]

    except Exception as e:
        state["ai_text_signal"] = AgentSignal(
            score=0.0, confidence=0.0,
            details=f"AI text detection failed: {e}",
            sources=[],
        )

    return state


def _parse_response(text: str):
    lines = {
        line.split(":")[0].strip(): ":".join(line.split(":")[1:]).strip()
        for line in text.splitlines()
        if ":" in line
    }
    score      = _safe_float(lines.get("AI_SCORE", "0.0"))
    confidence = _safe_float(lines.get("CONFIDENCE", "0.5"))
    reasoning  = lines.get("REASONING", text[:200])
    signals    = [s.strip() for s in lines.get("SIGNALS", "NONE").split(",")]
    return score, confidence, reasoning, signals


def _safe_float(val: str) -> float:
    try:
        return max(0.0, min(1.0, float(val)))
    except (ValueError, TypeError):
        return 0.0