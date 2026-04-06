"""
Image Forensics Agent
---------------------
Runs three parallel forensic checks on the image:
  1. ELA   — Error Level Analysis (local, Pillow)
  2. CNNDetect — AI-generation classifier (HuggingFace Inference API)
  3. C2PA  — Content Authenticity Initiative manifest check (c2pa-python)
"""
import io
import numpy as np
import requests
from PIL import Image

import config
from agents.state import AgentSignal, PipelineState


# ── 1. ELA ───────────────────────────────────────────────────────────────────

def ela_check(image_bytes: bytes) -> AgentSignal:
    """
    Re-save the image at a known JPEG quality and compute the absolute
    pixel difference. Manipulated regions retain higher-quality data and
    appear as bright patches.
    """
    try:
        original = Image.open(io.BytesIO(image_bytes)).convert("RGB")

        # Re-save at lower quality
        buffer = io.BytesIO()
        original.save(buffer, format="JPEG", quality=config.ELA_QUALITY)
        buffer.seek(0)
        resaved = Image.open(buffer).convert("RGB")

        orig_arr    = np.array(original,  dtype=np.float32)
        resave_arr  = np.array(resaved,   dtype=np.float32)
        diff        = np.abs(orig_arr - resave_arr)
        mean_diff   = float(diff.mean())
        max_diff    = float(diff.max())

        suspicious = mean_diff > config.ELA_THRESHOLD
        score      = min(mean_diff / (config.ELA_THRESHOLD * 3), 1.0)   # normalise 0–1

        return AgentSignal(
            score=score,
            confidence=0.70,
            details=(
                f"ELA mean diff: {mean_diff:.2f} (threshold {config.ELA_THRESHOLD}). "
                f"Max diff: {max_diff:.1f}. "
                + ("⚠ Suspicious regions detected." if suspicious else "✓ No obvious manipulation artifacts.")
            ),
            sources=["pillow-ela-local"],
        )
    except Exception as e:
        return AgentSignal(score=0.0, confidence=0.0, details=f"ELA failed: {e}", sources=[])


# ── 2. CNNDetect ─────────────────────────────────────────────────────────────

def cnndetect_check(image_bytes: bytes) -> AgentSignal:
    try:
        from huggingface_hub import InferenceClient
        client = InferenceClient(token=config.HF_TOKEN)
        
        result = client.image_classification(
            image=image_bytes,
            model="Wvolf/CNNDetect",
        )
        
        fake_score = next(
            (r.score for r in result if r.label.lower() in ("fake", "ai-generated")),
            None,
        )

        if fake_score is None:
            return AgentSignal(
                score=0.0, confidence=0.0,
                details="CNNDetect returned unexpected format.",
                sources=[config.HF_CNNDETECT_URL],
            )

        return AgentSignal(
            score=fake_score,
            confidence=0.75,
            details=(
                f"CNNDetect AI-generation probability: {fake_score:.0%}. "
                + ("⚠ Likely AI/GAN-generated." if fake_score > 0.6 else "✓ Probably a real photograph.")
            ),
            sources=[config.HF_CNNDETECT_URL],
        )
    except Exception as e:
        return AgentSignal(score=0.0, confidence=0.0, details=f"CNNDetect failed: {e}", sources=[])

# ── 3. C2PA ──────────────────────────────────────────────────────────────────

def c2pa_check(image_bytes: bytes) -> AgentSignal:
    try:
        import c2pa
        import io
        import json

        reader = c2pa.Reader("image/jpeg", io.BytesIO(image_bytes))
        manifest_json = reader.json()

        if not manifest_json:
            return AgentSignal(
                score=0.3, confidence=0.40,
                details="No C2PA/CAI provenance manifest found. Image has no digital signature chain.",
                sources=["c2pa-python-local"],
            )

        manifest = json.loads(manifest_json)
        claim_gen = manifest.get("claim_generator", "unknown")
        ai_generators = ["firefly", "dall-e", "stable-diffusion", "midjourney", "imagen"]
        is_ai = any(g in claim_gen.lower() for g in ai_generators)

        return AgentSignal(
            score=0.9 if is_ai else 0.1,
            confidence=0.90,
            details=(
                f"C2PA manifest found. Claim generator: '{claim_gen}'. "
                + ("⚠ Signed as AI-generated content." if is_ai else "✓ Signed as human-captured content.")
            ),
            sources=["c2pa-python-local"],
        )
    except ImportError:
        return AgentSignal(
            score=0.0, confidence=0.0,
            details="c2pa-python not installed.",
            sources=[],
        )
    except Exception as e:
        return AgentSignal(
            score=0.0, confidence=0.0,
            details=f"C2PA check failed: {e}",
            sources=[],
        )

# ── Main node ─────────────────────────────────────────────────────────────────

def forensics_agent(state: PipelineState) -> PipelineState:
    if not state.get("image_bytes"):
        state["ela_signal"]      = AgentSignal(score=0, confidence=0, details="No image bytes available.", sources=[])
        state["cnndetect_signal"]= AgentSignal(score=0, confidence=0, details="No image bytes available.", sources=[])
        state["c2pa_signal"]     = AgentSignal(score=0, confidence=0, details="No image bytes available.", sources=[])
        return state

    img = state["image_bytes"]
    state["ela_signal"]       = ela_check(img)
    state["cnndetect_signal"] = cnndetect_check(img)
    state["c2pa_signal"]      = c2pa_check(img)
    return state