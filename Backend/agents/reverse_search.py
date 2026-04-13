"""
Reverse Search Agent
--------------------
Disabled — returns neutral signal.
Claim verification and fact check handle search.
"""
from agents.state import AgentSignal, PipelineState


def reverse_search_agent(state: PipelineState) -> PipelineState:
    state["reverse_search_signal"] = AgentSignal(
        score=0.0,
        confidence=0.0,
        details="Reverse search disabled.",
        sources=[],
    )
    state["timeline"] = []
    return state