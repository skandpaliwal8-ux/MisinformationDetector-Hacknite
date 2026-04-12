"""
Groq Vision Agent
-----------------
Uses LLaMA 4 Scout (vision) on Groq to reason about the image —
looks for inconsistencies in lighting, shadows, faces, text, and
background artifacts that signal manipulation.
"""
from groq import Groq
import config
from agents.state import AgentSignal, PipelineState

_client = Groq(api_key=config.GROQ_API_KEY)

VISION_PROMPT = """You are an expert forensic image analyst.
Analyze this image carefully for signs of:
1. AI generation (unnatural textures, perfect symmetry, blurry backgrounds)
2. Photo manipulation (inconsistent lighting/shadows, copy-paste artifacts)
3. Contextual implausibility (text in image that looks wrong, impossible scenarios)

Respond in this EXACT format — no extra text:
MANIPULATION_SCORE: <0.0 to 1.0>
CONFIDENCE: <0.0 to 1.0>
FINDINGS: <one paragraph, under 80 words>
RED_FLAGS: <comma-separated list, or NONE>
"""


def groq_vision_agent(state: PipelineState) -> PipelineState:
    if not state.get("image_b64"):
        state["groq_vision_signal"] = AgentSignal(
            score=0.0, confidence=0.0,
            details="No image available for visual analysis.",
            sources=[],
        )
        return state

    try:
        response = _client.chat.completions.create(
            model=config.GROQ_VISION_MODEL,
            max_tokens=400,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{state['image_b64']}"
                        },
                    },
                    {"type": "text", "text": VISION_PROMPT},
                ],
            }],
        )

        raw = response.choices[0].message.content or ""
        score, confidence, findings, red_flags = _parse_vision_response(raw)

        state["groq_vision_signal"] = AgentSignal(
            score=score,
            confidence=confidence,
            details=findings,
            sources=[f"groq/{config.GROQ_VISION_MODEL}"],
        )

        # Append red flags to state for the synthesis agent
        existing_flags = state.get("red_flags") or []
        if red_flags and red_flags != ["NONE"]:
            state["red_flags"] = existing_flags + red_flags

    except Exception as e:
        state["groq_vision_signal"] = AgentSignal(
            score=0.0, confidence=0.0,
            details=f"Groq vision analysis failed: {e}",
            sources=[],
        )

    return state


# ── Parser ───────────────────────────────────────────────────────────────────

def _parse_vision_response(text: str):
    lines = {
        line.split(":")[0].strip(): ":".join(line.split(":")[1:]).strip()
        for line in text.splitlines()
        if ":" in line
    }

    score      = _safe_float(lines.get("MANIPULATION_SCORE", "0.0"))
    confidence = _safe_float(lines.get("CONFIDENCE", "0.5"))
    findings   = lines.get("FINDINGS", text[:300])
    red_flags  = [f.strip() for f in lines.get("RED_FLAGS", "NONE").split(",")]

    return score, confidence, findings, red_flags


def _safe_float(val: str) -> float:
    try:
        return max(0.0, min(1.0, float(val)))
    except (ValueError, TypeError):
        return 0.0