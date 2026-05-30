from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph

from app.config import settings
from app.graph.nodes import (
    analyze_node,
    check_escalation_node,
    classify_node,
    generate_response_node,
    human_review_node,
    resolve_node,
    retrieve_node,
    should_escalate,
)
from app.graph.state import SupportState


def build_graph() -> StateGraph:
    builder = StateGraph(SupportState)

    builder.add_node("classify", classify_node)
    builder.add_node("retrieve", retrieve_node)
    builder.add_node("analyze", analyze_node)
    builder.add_node("check_escalation", check_escalation_node)
    builder.add_node("generate_response", generate_response_node)
    builder.add_node("human_review", human_review_node)
    builder.add_node("resolve", resolve_node)

    builder.add_edge(START, "classify")
    builder.add_edge("classify", "retrieve")
    builder.add_edge("retrieve", "analyze")
    builder.add_edge("analyze", "check_escalation")

    builder.add_conditional_edges(
        "check_escalation",
        should_escalate,
        {"human_review": "human_review", "generate_response": "generate_response"},
    )

    builder.add_edge("generate_response", "resolve")
    builder.add_edge("human_review", "resolve")
    builder.add_edge("resolve", END)

    return builder


def compile_graph() -> object:
    builder = build_graph()
    checkpointer = PostgresSaver.from_conn_string(settings.database_url_sync)
    return builder.compile(checkpointer=checkpointer)


support_graph = compile_graph()
