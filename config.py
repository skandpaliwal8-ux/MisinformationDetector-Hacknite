import os
from dotenv import load_dotenv

load_dotenv()

# --- API Keys ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
HF_TOKEN = os.getenv("HF_TOKEN", "")
GOOGLE_FACT_CHECK_API_KEY = os.getenv("GOOGLE_FACT_CHECK_API_KEY", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")


SAPLING_API_URL = "https://api.sapling.ai/api/v1/aidetect"
SAPLING_API_KEY = os.getenv("SAPLING_API_KEY", "")  # free at sapling.ai


# --- Models ---
GROQ_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"   # best free vision on Groq
GROQ_TEXT_MODEL   = "llama-3.1-8b-instant"                        # fast synthesis
HF_CNNDETECT_URL = "https://api-inference.huggingface.co/models/umm-maybe/AI-image-detector"
# --- SearXNG (self-hosted) ---
SEARXNG_BASE_URL = os.getenv("SEARXNG_BASE_URL", "")

# --- Google Fact Check ---
FACT_CHECK_API_URL = "https://factchecktools.googleapis.com/v1alpha1/claims:search"

# --- ELA Settings ---
ELA_QUALITY = 90          # JPEG re-save quality for Error Level Analysis
ELA_THRESHOLD = 15.0      # Mean pixel diff above this → suspicious

# --- Scoring weights (must sum to 1.0) ---
WEIGHTS = {
    "ela":          0.20,
    "cnndetect":    0.20,
    "c2pa":         0.10,
    "reverse_search": 0.20,
    "fact_check":   0.20,
    "ai_text":      0.10,
}