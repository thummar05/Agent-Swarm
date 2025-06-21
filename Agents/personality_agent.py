from typing import TypedDict, List, Dict, Any, Optional, Annotated
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.graph import StateGraph, END
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

load_dotenv()

# Define the state specific to the Personality Agent
class PersonalityState(TypedDict):
    messages: Annotated[List[Any], add_messages]
    raw_agent_output: Optional[str]
    final_response: Optional[str]
    language: str

# Helper function to map OverallAgentState to PersonalityState
def map_to_personality_state(state: OverallAgentState) -> PersonalityState:
    """Maps the overall agent state to the PersonalityAgent's specific state."""
    return PersonalityState(
        messages=state["messages"],
        raw_agent_output=state.get("raw_agent_output"),
        final_response=None,
        language=state["language"]
    )

# Initialize LLM for personality application
llm_personality = ChatGoogleGenerativeAI(
    model="gemini-1.5-flash",
    temperature=0.5
)

# Node: Add Personality
def add_personality(state: PersonalityState) -> PersonalityState:
    """
    Applies a friendly and helpful personality to the raw agent output.
    Ensures responses are in the detected language.
    Handles initial greeting and direct replies for meta-questions (like "last question").
    """
    raw_output = state.get("raw_agent_output", "")
    current_messages = state["messages"]
    detected_lang = state.get("language", "en")
    final_response_content = ""

    # Check if the user is asking about a previous message/question
    if "last question was:" in raw_output.lower() or "sua última pergunta foi:" in raw_output.lower():
        final_response_content = raw_output
    else:
        system_prompt_content = load_prompt_template("personality_agent", detected_lang)
        system_message = SystemMessage(content=system_prompt_content)
        user_input_content = f"Raw agent output: {raw_output}"

        # We only pass the raw output to the personality LLM, not the full message history
        messages_for_llm = [
            system_message,
            HumanMessage(content=user_input_content)
        ]
        response = llm_personality.invoke(messages_for_llm)
        final_response_content = response.content

    return {
        **state,
        "final_response": final_response_content
    }

# Function to build and compile the Personality Agent graph
def build_personality_graph() -> StateGraph:
    """Builds the personality graph using LangGraph."""
    workflow = StateGraph(PersonalityState)
    workflow.add_node("add_personality", add_personality)
    workflow.set_entry_point("add_personality")
    workflow.add_edge("add_personality", END)
    return workflow.compile()
