import uuid
from datetime import datetime
from typing import TypedDict, List, Dict, Any, Optional, Annotated
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END, START
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from dotenv import load_dotenv
import re
import sys
import os

 
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.state import OverallAgentState
from utils.load_prompt import load_prompt_template
from utils.lang_detect import detect_language
from utils.extract_user_id import extract_user_id_from_query
from utils.validate_user import validate_user_access
from data.user_data import USER_DATABASE  

load_dotenv()

# Define the state specific to the Custom Agent
class CustomAgentState(TypedDict):
    messages: Annotated[List[Any], add_messages]
    session_user_id: str
    current_query_user_id: Optional[str]
    language: str
    tools_used: List[str]
    escalation_needed: bool
    user_data: Optional[Dict[str, Any]]
    current_query: str
    access_denied: bool

# Helper function to map OverallAgentState to CustomAgentState
def map_to_custom_agent_state(state: OverallAgentState) -> CustomAgentState:
    """Maps the overall agent state to the CustomAgent's specific state."""
    return CustomAgentState(
        messages=state["messages"],
        session_user_id=state["session_user_id"],
        current_query_user_id=state["current_query_user_id"],
        language=state["language"],
        tools_used=state["tools_used"],
        escalation_needed=state["escalation_needed"],
        user_data=state["user_data"],
        current_query=state["current_query"],
        access_denied=state["access_denied"]
    )

# Define tools for the Custom Agent using @tool decorator
@tool
def get_account_balance(user_id: str) -> Dict[str, Any]:
    """
    Get the current account balance for a given user.
    Args:
        user_id: The user's unique identifier.
    Returns:
        Dict containing success status, balance, and message.
    """
    try:
        if user_id not in USER_DATABASE:
            return {"success": False, "data": None, "message": "User not found"}
        balance = USER_DATABASE[user_id]["balance"]
        return {"success": True, "data": {"balance": balance}, "message": "Account balance retrieved successfully"}
    except Exception as e:
        return {"success": False, "data": None, "message": f"Error retrieving account balance: {str(e)}"}

@tool
def get_recent_transactions(user_id: str, limit: int = 5) -> Dict[str, Any]:
    """
    Get recent transactions for a user.
    Args:
        user_id: The user's unique identifier
        limit: Number of recent transactions to retrieve (default: 5)
    Returns:
        Dict containing success status, transaction data, and message
    """
    try:
        if user_id not in USER_DATABASE:
            return {"success": False, "data": None, "message": "User not found"}
        user_data = USER_DATABASE[user_id]
        # Sort transactions by date
        recent_transactions = sorted(
            user_data["transactions"],
            key=lambda x: datetime.strptime(x["date"], "%Y-%m-%d"),
            reverse=True
        )[:limit]
        return {"success": True, "data": {"transactions": recent_transactions}, "message": f"Retrieved {len(recent_transactions)} recent transactions"}
    except Exception as e:
        return {"success": False, "data": None, "message": f"Error retrieving transactions: {str(e)}"}

# Initialize LLM and bind tools
llm = ChatGoogleGenerativeAI(
    model="gemini-1.5-flash",
    temperature=0.3
)
tools = [get_account_balance, get_recent_transactions]
llm_with_tools = llm.bind_tools(tools)

# Node: Language Detection
def language_detector(state: CustomAgentState) -> CustomAgentState:
    """Detect the language of the current query and update state."""
    current_message = state["messages"][-1].content
    detected_lang = detect_language(current_message)
    return {**state, "language": detected_lang, "current_query": current_message}

# Node: User Access Validation
def user_access_validator(state: CustomAgentState) -> CustomAgentState:
    """Validate user access for account-related queries."""
    current_query = state["current_query"].lower()
    extracted_user_id = extract_user_id_from_query(current_query)
    account_access_keywords = ["balance", "saldo", "transaction", "transação", "history", "histórico", "extrato", "statement"]
    requires_account_access = any(keyword in current_query for keyword in account_access_keywords)
    access_denied = False
    current_query_user_id = None

    if requires_account_access:
        if extracted_user_id:
            current_query_user_id = extracted_user_id
            if not validate_user_access(state.get("session_user_id", ""), extracted_user_id):
                access_denied = True
        elif state.get("session_user_id"):
            current_query_user_id = state["session_user_id"]
        else:
            access_denied = True
    return {**state, "current_query_user_id": current_query_user_id, "access_denied": access_denied}

# Node: Topic Validation
def topic_validator(state: CustomAgentState) -> CustomAgentState:
    """Validate if the query is related to InfinityPay/banking services and specific to balance/transactions."""
    if state.get("access_denied", False):
        access_denied_message = AIMessage(content="""
            Desculpe, por motivos de segurança, você só pode acessar informações da sua própria conta.
            Se você deseja consultar dados de sua conta, certifique-se de:
            1. Ter fornecido seu User ID no início da sessão
            2. Estar perguntando sobre sua própria conta
            Como posso ajudá-lo com SUA conta do InfinityPay hoje?
            """) if state.get("language", "en") == "pt" else AIMessage(content="""
            I'm sorry, for security reasons, you can only access information from your own account.
            If you want to check your account data, please ensure you:
            1. Provided your User ID at the start of the session
            2. Are asking about your own account
            How can I help you with YOUR InfinityPay account today?
            """)
        return {**state, "messages": [access_denied_message], "escalation_needed": False}

    current_query = state["current_query"].lower()
    balance_transaction_keywords = ["balance", "saldo", "transaction", "transação", "history", "histórico", "extrato", "current balance", "últimas transações", "movimentação"]
    has_relevant_context = any(keyword in current_query for keyword in balance_transaction_keywords)

    if not has_relevant_context:
        rejection_message = AIMessage(content="""
            Desculpe, sou especializado em saldo e histórico de transações.
            Para outras questões, por favor, me diga mais ou tente perguntar de outra forma.
            """) if state.get("language", "en") == "pt" else AIMessage(content="""
            I'm sorry, I specialize in account balance and transaction history.
            For other inquiries, please tell me more or try asking in a different way.
            """)
        return {**state, "messages": [rejection_message], "escalation_needed": False}
    return state

# Node: Main Custom Agent LLM Interaction
def custom_agent_node(state: CustomAgentState) -> CustomAgentState:
    """Main custom agent node with LLM and tools for balance/transactions."""
    system_prompt_content = load_prompt_template("custom_agent", state.get("language", "en"))
    system_message = SystemMessage(content=system_prompt_content)
    messages = [system_message] + state["messages"]

    user_id_to_use = state.get("current_query_user_id") or state.get("session_user_id")
    if user_id_to_use:
        messages.append(HumanMessage(content=f"[System Context: Authorized User ID for this query: {user_id_to_use}]"))

    response = llm_with_tools.invoke(messages)

    tools_used = state.get("tools_used", [])
    if hasattr(response, 'tool_calls') and response.tool_calls:
        for tool_call in response.tool_calls:
            if tool_call['name'] not in tools_used:
                tools_used.append(tool_call['name'])

    return {**state, "messages": [response], "tools_used": tools_used}

# Conditional Edge: Determine if agent should continue to tools or end
def should_continue(state: CustomAgentState) -> str:
    """Determine if we should continue to tools or end the Custom Agent graph."""
    last_message = state["messages"][-1]
    if (hasattr(last_message, 'content') and isinstance(last_message, AIMessage) and
        any(phrase in last_message.content for phrase in [
            "I'm sorry, I specialize in account balance and transaction history",
            "Desculpe, sou especializado em saldo e histórico de transações",
            "for security reasons",
            "por motivos de segurança"
        ])):
        return "end"  
    if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        return "tools" 
    return "end"  

# Function to build and compile the Custom Agent graph
def build_custom_agent_graph() -> StateGraph:
    """Build the custom agent graph using LangGraph."""
    workflow = StateGraph(CustomAgentState)

    # Add nodes to the workflow
    workflow.add_node("language_detector", language_detector)
    workflow.add_node("user_access_validator", user_access_validator)
    workflow.add_node("topic_validator", topic_validator)
    workflow.add_node("custom_agent", custom_agent_node)
    workflow.add_node("tools", ToolNode(tools)) # ToolNode automatically executes tools based on LLM output

    # Define the entry point for the graph
    workflow.set_entry_point("language_detector")

    # Define edges between nodes
    workflow.add_edge("language_detector", "user_access_validator")
    workflow.add_edge("user_access_validator", "topic_validator")

    # Conditional edge from topic_validator: proceed to custom_agent or end
    workflow.add_conditional_edges(
        "topic_validator",
        lambda state: "end" if (
            hasattr(state["messages"][-1], 'content') and
            isinstance(state["messages"][-1], AIMessage) and
            any(phrase in state["messages"][-1].content for phrase in [
                "I'm sorry, I specialize", "Desculpe, sou especializado",
                "for security reasons", "por motivos de segurança"
            ])
        ) else "custom_agent",
        {"custom_agent": "custom_agent", "end": END}
    )

    # Conditional edge from custom_agent: proceed to tools or end
    workflow.add_conditional_edges("custom_agent", should_continue, {"tools": "tools", "end": END})

    # Edge from tools back to custom_agent to process tool output
    workflow.add_edge("tools", "custom_agent")

    return workflow.compile()
