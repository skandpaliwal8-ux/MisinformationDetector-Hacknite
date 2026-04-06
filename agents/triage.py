import base64
import httpx
from agents.state import PipelineState

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff")
IMAGE_DOMAINS = ("gstatic.com", "imgur.com", "pbs.twimg.com", "i.redd.it", "cdninstagram.com")


def triage_agent(state: PipelineState) -> PipelineState:
    raw = state["raw_input"].strip()

    if _is_image_url(raw):
        state["input_type"] = "image_url"
        img_bytes, content_type = _download(raw)
        if img_bytes:
            state["image_bytes"] = img_bytes
            state["image_b64"] = base64.b64encode(img_bytes).decode("utf-8")
        else:
            state["error"] = f"Could not download image from {raw}"

    elif raw.startswith("http"):
        state["input_type"] = "article_url"

    else:
        state["input_type"] = "text_claim"

    return state


def _is_image_url(url: str) -> bool:
    url_lower = url.lower()

    # Check file extension (before query params)
    path = url_lower.split("?")[0]
    if path.endswith(IMAGE_EXTENSIONS):
        return True

    # Check known image hosting domains
    if any(domain in url_lower for domain in IMAGE_DOMAINS):
        return True

    # Check for image-related query params (Google, Bing thumbnails)
    if "gstatic.com/images" in url_lower:
        return True
    if "tbn:" in url_lower or "encrypted-tbn" in url_lower:
        return True

    return False


def _download(url: str):
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            r = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            content_type = r.headers.get("content-type", "")
            return r.content, content_type
    except Exception:
        return None, None