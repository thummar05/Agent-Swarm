from typing import TypedDict, List, Dict, Any, Annotated, Optional
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.graph import StateGraph, END, START
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph.message import add_messages
from dotenv import load_dotenv
import sys
import os

# Adjust sys.path for project root if necessary
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.state import OverallAgentState
from utils.load_prompt import load_prompt_template
from utils.lang_detect import detect_language

load_dotenv()

# Initialize the LLM for routing decisions
llm_router = ChatGoogleGenerativeAI(
    model="gemini-1.5-flash",
    temperature=0.1
)

# This node directly accepts and returns OverallAgentState
def route_agent(state: OverallAgentState) -> OverallAgentState:
    """
    Analyzes the incoming message and decides which specialized agent
    (Custom, CustomerSupport or Knowledge) is best suited to handle it.
    """
    current_message = state["messages"][-1].content
    detected_lang = detect_language(current_message)

    state["language"] = detected_lang

    # Load routing prompt from file
    routing_prompt_template = load_prompt_template("router_agent", detected_lang)
    routing_prompt = routing_prompt_template.format(current_message=current_message)

    response = llm_router.invoke(routing_prompt)
    chosen_agent = response.content.strip().lower()


    state["next_agent"] = chosen_agent
    state["language"] = detected_lang

    return state

def build_router_graph() -> StateGraph:
    """Builds the router graph using LangGraph."""
    workflow = StateGraph(OverallAgentState)
    workflow.add_node("route", route_agent)
    workflow.set_entry_point("route")
    workflow.add_edge("route", END)
    return workflow.compile()
