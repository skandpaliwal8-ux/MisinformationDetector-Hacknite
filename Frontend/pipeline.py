from langgraph.graph import StateGraph, END
from agents.state import PipelineState
from agents.triage         import triage_agent
from agents.forensics      import forensics_agent
from agents.vision         import groq_vision_agent
from agents.reverse_search import reverse_search_agent
from agents.context        import context_agent, claims_extraction_agent
from agents.fact_check     import fact_check_agent
from agents.ai_text        import ai_text_agent
from agents.synthesis      import synthesis_agent
from agents.claim_verifier import claim_verifier_agent


def _route_after_triage(state: PipelineState) -> str:
    t = state.get("input_type", "text_claim")
    if state.get("error"):
        return "synthesis"
    if t == "image_url":
        return "forensics"
    if t == "article_url":
        return "context"
    return "claims"


def build_pipeline() -> StateGraph:
    graph = StateGraph(PipelineState)

    # --- Register nodes ---
    graph.add_node("triage",          triage_agent)
    graph.add_node("forensics",       forensics_agent)
    graph.add_node("vision",          groq_vision_agent)
    graph.add_node("reverse_search",  reverse_search_agent)
    graph.add_node("context",         context_agent)
    graph.add_node("claims",          claims_extraction_agent)
    graph.add_node("claim_verifier",  claim_verifier_agent)
    graph.add_node("fact_check",      fact_check_agent)
    graph.add_node("ai_text",         ai_text_agent)
    graph.add_node("synthesis",       synthesis_agent)

    # --- Entry point ---
    graph.set_entry_point("triage")

    # --- Conditional routing after triage ---
    graph.add_conditional_edges(
        "triage",
        _route_after_triage,
        {
            "forensics": "forensics",
            "context":   "context",
            "claims":    "claims",
            "synthesis": "synthesis",
        },
    )

    # --- Image path ---
    graph.add_edge("forensics",      "vision")
    graph.add_edge("vision",         "reverse_search")
    graph.add_edge("reverse_search", "synthesis")

    # --- Article path ---
    graph.add_edge("context",        "claims")
    graph.add_edge("claims",         "claim_verifier")
    graph.add_edge("claim_verifier", "fact_check")
    graph.add_edge("fact_check",     "ai_text")
    graph.add_edge("ai_text",        "synthesis")

    # --- Final node ---
    graph.add_edge("synthesis", END)

    return graph.compile()


PIPELINE = build_pipeline()


def run_pipeline(raw_input: str) -> PipelineState:
    initial_state: PipelineState = {
        "input_type":            "",
        "raw_input":             raw_input,
        "image_bytes":           None,
        "image_b64":             None,
        "article_text":          None,
        "ela_signal":            None,
        "cnndetect_signal":      None,
        "c2pa_signal":           None,
        "groq_vision_signal":    None,
        "reverse_search_signal": None,
        "fact_check_signal":     None,
        "ai_text_signal":        None,
        "verdict":               None,
        "confidence_score":      0.0,
        "summary":               None,
        "red_flags":             [],
        "timeline":              [],
        "error":                 None,
    }
    return PIPELINE.invoke(initial_state)