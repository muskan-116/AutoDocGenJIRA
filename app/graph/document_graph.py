# app/graph/workflow_graph.py
from langgraph.graph import StateGraph, START, END
from app.graph.nodes.pm_agent import fetch_pm_data_node
from app.graph.nodes.doc_agent import create_docs_node  # import doc node
from typing import TypedDict, List, Dict

class WorkflowState(TypedDict):
    project_id: str
    user_trello_key: str
    user_trello_token: str
    uploaded_pdf_bytes: bytes
    pdf_headings: List[str]
    selected_headings: List[str]
    pm_data: Dict
    generated_docs: str

graph = StateGraph(WorkflowState)

# Add nodes
graph.add_node("pm_agent", fetch_pm_data_node)
graph.add_node("doc_agent", create_docs_node)  # add doc node

# Add edges
graph.add_edge(START, "pm_agent")
graph.add_edge("pm_agent", "doc_agent")  # flow pm_agent → doc_agent
graph.add_edge("doc_agent", END)          # doc_agent → END

workflow = graph.compile()
