from typing import TypedDict, List, Dict, Any, Annotated, Optional
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.graph import StateGraph, END, START
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph.message import add_messages
from dotenv import load_dotenv
import sys
import os
import re

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

# Suspicious patterns that should trigger Slack agent
SUSPICIOUS_PATTERNS = [
    r'(give|grant|provide).*access.*account',
    r'bypass.*security',
    r'override.*system',
    r'disable.*authentication',
    r'skip.*verification',
    r'access.*without.*permission',
    r'hack.*account',
    r'steal.*data',
    r'unauthorized.*access',
    r'break.*into.*system',
    r'exploit.*vulnerability',
    r'password.*for.*account',
    r'login.*credentials',
    r'administrative.*privileges',
    r'root.*access',
    r'backdoor.*access'
]

def is_suspicious_query(message: str) -> bool:
    """Check if the message contains suspicious patterns."""
    message_lower = message.lower()
    
    for pattern in SUSPICIOUS_PATTERNS:
        if re.search(pattern, message_lower):
            return True
    
    return False

def route_agent(state: OverallAgentState) -> OverallAgentState:
    """
    Analyzes the incoming message and decides which specialized agent
    (Custom, CustomerSupport, Knowledge, or Slack) is best suited to handle it.
    """
    current_message = state["messages"][-1].content
    detected_lang = detect_language(current_message)

    state["language"] = detected_lang

    # First check for suspicious content
    if is_suspicious_query(current_message):
        print(f"🚨 Suspicious query detected: {current_message[:100]}...")
        state["next_agent"] = "slack_agent"
        state["language"] = detected_lang
        return state

    # Load routing prompt from file for normal routing
    routing_prompt_template = load_prompt_template("router_agent", detected_lang)
    
    # Enhanced routing prompt that includes Slack agent option
    enhanced_routing_prompt = f"""
    {routing_prompt_template.format(current_message=current_message)}
    
    Additionally, if the message contains any suspicious content that could be:
    - Requesting unauthorized access to accounts
    - Trying to bypass security measures
    - Asking for sensitive information inappropriately
    - Attempting social engineering
    
    You should route to 'slack_agent' for security review.
    
    Available agents:
    - customer_support: For general customer support queries
    - knowledge_agent: For information retrieval and Q&A
    - custom_agent: For complex tasks and custom requests
    - slack_agent: For suspicious or security-related concerns
    - default: For general conversation
    
    Respond with only the agent name in lowercase.
    """

    response = llm_router.invoke(enhanced_routing_prompt)
    chosen_agent = response.content.strip().lower()

    # Validate the chosen agent
    valid_agents = ["customer_support", "knowledge_agent", "custom_agent", "slack_agent", "default"]
    if chosen_agent not in valid_agents:
        chosen_agent = "default"

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