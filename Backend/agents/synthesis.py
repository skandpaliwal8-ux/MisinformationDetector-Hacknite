"""
Synthesis Agent
---------------
Reads all agent signals, resolves conflicts, and produces the final:
  - verdict: REAL | MISLEADING | FAKE | UNCERTAIN
  - confidence_score: 0–100
  - summary: 2–3 sentence plain-language explanation
Uses a weighted average of signal scores + Groq LLaMA for narrative.
"""
from groq import Groq
import config
from agents.state import AgentSignal, PipelineState

_client = Groq(api_key=config.GROQ_API_KEY)

SYNTHESIS_PROMPT = """You are a senior fact-checking editor reviewing an automated analysis report.

Agent signals received:
{signals}

Red flags detected:
{red_flags}

Based on these signals, write a concise 2–3 sentence verdict summary for a general audience.
Be direct about what the evidence shows. Acknowledge uncertainty where it exists.
Do NOT use bullet points. Do NOT repeat numbers already in the signals.
End with a clear recommendation: "We recommend treating this as [real/unreliable/unverified]."
"""


DISPLAY_NAMES = {
    "ela_signal":            "ELA Forensics",
    "cnndetect_signal":      "CNNDetect",
    "c2pa_signal":           "C2PA Provenance",
    "groq_vision_signal":    "Visual Analysis",
    "reverse_search_signal": "Reverse Search",
    "fact_check_signal":     "Fact Check",
    "ai_text_signal":        "AI Text Detection",
    "claim_verify_signal":   "Claim Verification",
}


def synthesis_agent(state: PipelineState) -> PipelineState:
    weighted_sum = 0.0
    total_weight = 0.0
    signals_text = []

    for signal_key, weight in config.WEIGHTS.items():
        signal = state.get(signal_key)
        if signal and signal.get("confidence", 0) > 0:
            # Effective weight is the configured weight scaled by agent confidence
            w = weight * signal["confidence"]
            weighted_sum += signal["score"] * w
            total_weight += w
            
            name = DISPLAY_NAMES.get(signal_key, signal_key)
            signals_text.append(
                f"  [{name}] score={signal['score']:.2f} "
                f"confidence={signal['confidence']:.2f} — {signal['details'][:120]}"
            )

    composite = weighted_sum / total_weight if total_weight > 0 else 0.0

    # --- Override: if claim verification or fact check strongly flags fake, force the verdict ---
    claim_verify = state.get("claim_verify_signal")
    fact_check   = state.get("fact_check_signal")

    if claim_verify and claim_verify["score"] >= 0.65:
        composite = max(composite, claim_verify["score"])

    if fact_check and fact_check["score"] >= 0.65:
        composite = max(composite, fact_check["score"])

    # If both agree it's fake, push to maximum
    if (claim_verify and claim_verify["score"] >= 0.65 and
            fact_check and fact_check["score"] >= 0.50):
        composite = max(composite, 0.85)

    confidence_score = round(composite * 100, 1)

    # --- Verdict label ---
    if confidence_score >= 70:
        verdict = "FAKE"
    elif confidence_score >= 45:
        verdict = "MISLEADING"
    elif confidence_score >= 20:
        verdict = "UNCERTAIN"
    else:
        verdict = "REAL"

    summary = _generate_summary(signals_text, state.get("red_flags") or [], verdict, confidence_score)

    state["verdict"]          = verdict
    state["confidence_score"] = confidence_score
    state["summary"]          = summary

    return state


def _generate_summary(signals: list[str], flags: list[str], verdict: str, score: float) -> str:
    try:
        resp = _client.chat.completions.create(
            model=config.GROQ_TEXT_MODEL,
            max_tokens=250,
            messages=[{
                "role": "user",
                "content": SYNTHESIS_PROMPT.format(
                    signals="\n".join(signals) or "No signals available.",
                    red_flags="\n".join(f"  • {f}" for f in flags) or "  None detected.",
                ),
            }],
        )
        return resp.choices[0].message.content or _fallback_summary(verdict, score)
    except Exception:
        return _fallback_summary(verdict, score)


def _fallback_summary(verdict: str, score: float) -> str:
    return (
        f"Automated analysis produced a composite manipulation score of {score:.1f}/100. "
        f"Overall verdict: {verdict}. "
        "Manual review is recommended for high-stakes decisions."
    )