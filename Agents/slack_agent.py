import os
import requests
from typing import TypedDict, List, Dict, Any, Optional
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.graph import StateGraph, END, START
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv
import sys
import re

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.state import OverallAgentState

load_dotenv()

# Environment variables
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")

# Initialize LLM for generating responses
llm_slack_agent = ChatGoogleGenerativeAI(
    model="gemini-1.5-flash",
    temperature=0.3
)

class SlackAgentState(TypedDict):
    """State specific to the Slack escalation agent."""
    messages: List[Any]
    session_user_id: str
    current_query: str
    language: str
    validation_passed: bool
    slack_notification_sent: bool
    actual_tool_outputs: Dict[str, Any]

def send_slack_notification(user_id: str, message: str) -> str:
    """Send notification to Slack about suspicious activity."""
    if not SLACK_WEBHOOK_URL:
        return "Slack webhook URL not configured"
    
    payload = {
        "text": f"🚨 *Suspicious Activity Detected* 🚨\n\n*User:* {user_id}\n*Message:* {message}"
    }
    try:
        response = requests.post(SLACK_WEBHOOK_URL, json=payload)
        response.raise_for_status()
        return "✅ Slack alert sent successfully"
    except Exception as e:
        return f"Slack notification failed: {str(e)}"

def validate_with_guardrails(user_input: str, llm_response: str) -> Dict[str, Any]:
    """Validate LLM response using custom validation logic (replaces Guardrails)."""
    try:
        validation_passed = False  
        
        error_details = []
        if not validation_passed:
            error_details.append("Custom validation failed - simulating guardrails behavior")
        
        return {
            "validation_passed": validation_passed,
            "error_details": error_details,
            "validated_output": llm_response
        }
        
    except Exception as e:
        return {
            "validation_passed": False,
            "error_details": [f"Validation error: {str(e)}"],
            "validated_output": llm_response
        }

def slack_agent_node(state: SlackAgentState) -> SlackAgentState:
    """Main node that processes suspicious queries and handles escalation."""
    current_query = state["current_query"]
    user_id = state["session_user_id"]
    language = state.get("language", "en")
    

    system_prompt = """You are a helpful AI assistant for InfinityPay. 
    Respond to the user's query professionally and helpfully. 
    Do not provide any sensitive information or access to accounts without proper verification."""
    
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=current_query)
    ]
    
    llm_response = llm_slack_agent.invoke(messages)
    generated_response = llm_response.content
    
    # Validate the response with custom validation (replacing Guardrails)
    validation_result = validate_with_guardrails(current_query, generated_response)
    
    state["validation_passed"] = validation_result["validation_passed"]
    state["actual_tool_outputs"] = {
        "llm_generation": generated_response,
        "guardrails_validation": "Passed" if validation_result["validation_passed"] else "Failed"
    }
    
    # If validation fails, send Slack notification
    if not validation_result["validation_passed"]:
        slack_result = send_slack_notification(user_id, current_query)
        state["slack_notification_sent"] = True
        state["actual_tool_outputs"]["slack_notification"] = slack_result
        state["actual_tool_outputs"]["guardrails_violations"] = validation_result["error_details"]
        
        # Use escalation response instead of original
        final_response = "⚠️ Your request has been flagged for review and escalated to our security team. A human agent will contact you shortly."
    else:
        state["slack_notification_sent"] = False
        final_response = validation_result["validated_output"]
    
    # Add the final response to messages
    state["messages"].append(AIMessage(content=final_response))
    
    return state

def map_to_slack_agent_state(overall_state: OverallAgentState) -> SlackAgentState:
    """Map overall state to Slack agent specific state."""
    return SlackAgentState(
        messages=overall_state["messages"].copy(),
        session_user_id=overall_state["session_user_id"],
        current_query=overall_state["current_query"],
        language=overall_state["language"],
        validation_passed=True,  
        slack_notification_sent=False,  
        actual_tool_outputs={}
    )

def build_slack_agent_graph() -> StateGraph:
    """Build the Slack escalation agent graph."""
    workflow = StateGraph(SlackAgentState)
    workflow.add_node("slack_agent", slack_agent_node)
    workflow.set_entry_point("slack_agent")
    workflow.add_edge("slack_agent", END)
    return workflow.compile()