"""
Context & Article Scraping Agent
----------------------------------
- For article URLs: scrapes the text with Trafilatura
- For image URLs: tries to find surrounding article context
- Extracts main claims from the text using Groq
"""
import trafilatura
from groq import Groq
import config
from agents.state import AgentSignal, PipelineState

_client = Groq(api_key=config.GROQ_API_KEY)

CLAIM_EXTRACTION_PROMPT = """You are a fact-checking assistant.
Extract the 3 most specific, verifiable factual claims from this text.
Focus ONLY on concrete, checkable facts like:
- Specific statistics or numbers ("unemployment rose to 8%")
- Specific events with dates ("the bill was passed on March 3rd")
- Specific attributions ("the WHO stated that...")
- Cause-effect claims ("X caused Y")

Avoid vague or opinion-based statements.

Text:
{text}

Respond in this EXACT format:
CLAIM_1: <specific verifiable claim>
CLAIM_2: <specific verifiable claim>
CLAIM_3: <specific verifiable claim>
"""


def context_agent(state: PipelineState) -> PipelineState:
    url = state.get("raw_input", "")
    input_type = state.get("input_type", "")

    if input_type not in ("article_url",):
        # Nothing to scrape for plain images or text claims
        return state

    text = _scrape(url)
    if not text:
        return state

    state["article_text"] = text
    return state


def _scrape(url: str) -> str | None:
    try:
        downloaded = trafilatura.fetch_url(url)
        return trafilatura.extract(downloaded) if downloaded else None
    except Exception:
        return None


def claims_extraction_agent(state: PipelineState) -> PipelineState:
    input_type = state.get("input_type")
    
    # For text claims — use the raw input directly, no extraction needed
    if input_type == "text_claim":
        raw = state.get("raw_input", "").strip()
        if raw:
            state["_extracted_claims"] = [raw]
        else:
            state["_extracted_claims"] = []
        return state

    # For articles — extract claims from scraped text
    text = state.get("article_text", "")
    
    if not text or len(text.strip()) < 20:
        state["_extracted_claims"] = []
        return state

    try:
        resp = _client.chat.completions.create(
            model=config.GROQ_TEXT_MODEL,
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": CLAIM_EXTRACTION_PROMPT.format(text=text[:3000]),
            }],
        )
        raw = resp.choices[0].message.content or ""
        claims = _parse_claims(raw)
        state["_extracted_claims"] = claims if claims else [text[:200]]
    except Exception:
        state["_extracted_claims"] = []

    return state


def _parse_claims(text: str) -> list[str]:
    claims = []
    for line in text.splitlines():
        for prefix in ("CLAIM_1:", "CLAIM_2:", "CLAIM_3:"):
            if line.startswith(prefix):
                claim = line.replace(prefix, "").strip()
                if claim:
                    claims.append(claim)
    return claims