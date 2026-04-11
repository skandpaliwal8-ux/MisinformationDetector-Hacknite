from typing import Optional, Dict, Any, List
from typing_extensions import TypedDict


class AgentSignal(TypedDict):
    score: float          # 0.0 (clean/real) → 1.0 (fake/manipulated)
    confidence: float     # how sure is this agent (0–1)
    details: str          # human-readable explanation
    sources: List[str]    # URLs or tool names used


class PipelineState(TypedDict):
    input_type:    str
    raw_input:     str
    image_bytes:   Optional[bytes]
    image_b64:     Optional[str]
    article_text:  Optional[str]

    ela_signal:              Optional[AgentSignal]
    cnndetect_signal:        Optional[AgentSignal]
    c2pa_signal:             Optional[AgentSignal]
    groq_vision_signal:      Optional[AgentSignal]
    reverse_search_signal:   Optional[AgentSignal]
    fact_check_signal:       Optional[AgentSignal]
    ai_text_signal:          Optional[AgentSignal]
    claim_verify_signal:     Optional[AgentSignal]

    extracted_claims:        Optional[list]       # removed underscore
    verification_results:    Optional[list]       # removed underscore

    verdict:          Optional[str]
    confidence_score: float
    summary:          Optional[str]
    red_flags:        List[str]
    timeline:         List[Dict[str, Any]]
    error:            Optional[str]