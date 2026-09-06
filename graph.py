"""
LangGraph state graph wiring the five agents.

    classify -> retrieve -> verify_freshness -> check_scams -> compose

Linear by design. explain.md specifies this exact chain, and a linear graph is
auditable: for any answer you can point at which node produced which fact. The
one piece of routing is that classify may short-circuit to compose when it
cannot identify the service - there is nothing to retrieve for a category we do
not cover, and guessing is the failure mode this project exists to avoid.
"""
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph

from agents.freshness_agent import assess
from agents.intent_classifier import classify
from agents.response_composer import compose
from agents.retrieval_agent import retrieve
from agents.scam_pattern_agent import lookup


class GSNAState(TypedDict, total=False):
    query: str
    intent: Dict[str, Any]
    retrieved: Dict[str, Any]
    freshness: Dict[str, Any]
    scams: List[Dict[str, Any]]
    answer: str
    trace: List[str]


def _trace(state, msg):
    state.setdefault("trace", []).append(msg)


def node_classify(state: GSNAState) -> GSNAState:
    intent = classify(state["query"])
    _trace(state, f"classify -> {intent['category']} ({intent['method']}, {intent['confidence']:.3f})")
    return {"intent": intent, "trace": state["trace"]}


def node_retrieve(state: GSNAState) -> GSNAState:
    r = retrieve(state["query"], state["intent"]["category"])
    _trace(state, f"retrieve -> {len(r['chunks'])} chunks, record={'yes' if r['record'] else 'no'}")
    return {"retrieved": r, "trace": state["trace"]}


def node_freshness(state: GSNAState) -> GSNAState:
    f = assess(state["retrieved"].get("record"))
    _trace(state, f"freshness -> {f['level']}")
    return {"freshness": f, "trace": state["trace"]}


def node_scams(state: GSNAState) -> GSNAState:
    s = lookup(state["intent"]["category"])
    _trace(state, f"scams -> {len(s)} curated entr(y/ies)")
    return {"scams": s, "trace": state["trace"]}


def node_compose(state: GSNAState) -> GSNAState:
    a = compose(state["query"], state["intent"], state.get("retrieved", {"record": None}),
                state.get("freshness", {"level": "none", "notes": []}), state.get("scams", []))
    _trace(state, f"compose -> {len(a)} chars")
    return {"answer": a, "trace": state["trace"]}


def route_after_classify(state: GSNAState) -> str:
    return "compose" if state["intent"]["category"] in ("unknown_service", "out_of_scope") else "retrieve"


def build_graph():
    g = StateGraph(GSNAState)
    g.add_node("classify", node_classify)
    g.add_node("retrieve", node_retrieve)
    g.add_node("verify_freshness", node_freshness)
    g.add_node("check_scams", node_scams)
    g.add_node("compose", node_compose)

    g.set_entry_point("classify")
    g.add_conditional_edges("classify", route_after_classify,
                            {"retrieve": "retrieve", "compose": "compose"})
    g.add_edge("retrieve", "verify_freshness")
    g.add_edge("verify_freshness", "check_scams")
    g.add_edge("check_scams", "compose")
    g.add_edge("compose", END)
    return g.compile()


_app = None


def answer(query: str) -> GSNAState:
    global _app
    if _app is None:
        _app = build_graph()
    return _app.invoke({"query": query, "trace": []})


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "How do I renew my passport and how much does it cost?"
    out = answer(q)
    print("\n".join(f"  [{t}]" for t in out["trace"]))
    print("\n" + "=" * 78 + "\n")
    print(out["answer"])
