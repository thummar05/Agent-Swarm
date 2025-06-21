import uuid
import smtplib
from email.mime.text import MIMEText
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

# Adjust sys.path for project root if necessary
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

 
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_EMAIL_PASSWORD = os.getenv("SENDER_EMAIL_PASSWORD")
RECIPIENT_EMAIL = "thummarraj0511@gmail.com"  
SMTP_SERVER = os.getenv("SMTP_SERVER") 

if not SENDER_EMAIL or not SENDER_EMAIL_PASSWORD or not SMTP_SERVER:
    print("Warning: Missing email configuration. Support ticket email functionality may be limited.")

# Define the state specific to the Customer Support Agent
class CustomerSupportState(TypedDict):
    messages: Annotated[List[Any], add_messages]
    session_user_id: str
    current_query_user_id: Optional[str]
    language: str
    tools_used: List[str]
    escalation_needed: bool
    user_data: Optional[Dict[str, Any]]
    current_query: str
    access_denied: bool

# Helper function to map OverallAgentState to CustomerSupportState
def map_to_customer_support_state(state: OverallAgentState) -> CustomerSupportState:
    """Maps the overall agent state to the CustomerSupportAgent's specific state."""
    return CustomerSupportState(
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

 
TICKETS_DATABASE = {}

 
@tool
def get_user_info(user_id: str) -> Dict[str, Any]:
    """
    Get general user information.
    Args:
        user_id: The user's unique identifier
    Returns:
        Dict containing success status, user data, and message
    """
    try:
        if user_id not in USER_DATABASE:
            return {"success": False, "data": None, "message": "User not found"}
        user_data = USER_DATABASE[user_id]
        safe_user_data = {
            "name": user_data["name"],
            "email": user_data["email"],
            "account_status": user_data["account_status"],
            "created_date": user_data["created_date"]
        }
        return {"success": True, "data": safe_user_data, "message": "User information retrieved successfully"}
    except Exception as e:
        return {"success": False, "data": None, "message": f"Error retrieving user info: {str(e)}"}

@tool
def create_support_ticket(user_id: str, issue_description: str, priority: str = "medium") -> Dict[str, Any]:
    """
    Create a support ticket for escalation and send an email notification.
    Args:
        user_id: The user's unique identifier
        issue_description: Description of the issue
        priority: Priority level (low, medium, high)
    Returns:
        Dict containing success status, ticket data, and message
    """
    try:
        ticket_id = str(uuid.uuid4())
        ticket_data = {
            "ticket_id": ticket_id,
            "user_id": user_id,
            "issue_description": issue_description,
            "priority": priority,
            "status": "open",
            "created_at": datetime.now().isoformat(),
        }
        TICKETS_DATABASE[ticket_id] = ticket_data

        # Email Sending Logic  
        if SENDER_EMAIL and SENDER_EMAIL_PASSWORD and SMTP_SERVER:
            user_info = USER_DATABASE.get(user_id, {})
            user_name = user_info.get("name", "N/A")
            user_email = user_info.get("email", "N/A")
            user_phone = user_info.get("phone", "N/A")

            email_subject = f"New Support Ticket Created: {ticket_id} - User: {user_name}"
            email_body = f"""
            Dear Support Team,
            A new support ticket has been created with the following details:
            Ticket ID: {ticket_id}
            User ID: {user_id}
            User Name: {user_name}
            User Email: {user_email}
            User Phone: {user_phone}
            Issue Description: {issue_description}
            Priority: {priority}
            Status: {ticket_data['status']}
            Created At: {ticket_data['created_at']}
            Please investigate this issue and respond to the user as soon as possible.
            Regards,
            Customer Support Agent
            """
            msg = MIMEText(email_body)
            msg['Subject'] = email_subject
            msg['From'] = SENDER_EMAIL
            msg['To'] = RECIPIENT_EMAIL

            try:
                with smtplib.SMTP_SSL(SMTP_SERVER, 465) as smtp:
                    smtp.login(SENDER_EMAIL, SENDER_EMAIL_PASSWORD)
                    smtp.send_message(msg)
                print(f"Email sent successfully for ticket {ticket_id} to {RECIPIENT_EMAIL}")
            except Exception as email_e:
                print(f"Failed to send email for ticket {ticket_id}: {email_e}")
        else:
            print("Email configuration missing, skipping email notification.")

        return {"success": True, "data": {"ticket_id": ticket_id}, "message": f"Support ticket {ticket_id} created successfully." + (" Email notification sent." if SENDER_EMAIL and SENDER_EMAIL_PASSWORD and SMTP_SERVER else "")}
    except Exception as e:
        return {"success": False, "data": None, "message": f"Error creating support ticket: {str(e)}"}

# Initialize LLM and bind tools
llm = ChatGoogleGenerativeAI(
    model="gemini-1.5-flash",
    temperature=0.3
)
tools = [get_user_info, create_support_ticket]
llm_with_tools = llm.bind_tools(tools)

# Node: Language Detection
def language_detector(state: CustomerSupportState) -> CustomerSupportState:
    """Detect the language of the current query and update state."""
    current_message = state["messages"][-1].content
    detected_lang = detect_language(current_message)
    return {**state, "language": detected_lang, "current_query": current_message}

# Node: User Access Validation
def user_access_validator(state: CustomerSupportState) -> CustomerSupportState:
    """Validate user access for account-related queries for Customer Support Agent."""
    current_query = state["current_query"].lower()
    extracted_user_id = extract_user_id_from_query(current_query)
    account_access_keywords = [
        "account", "conta", "statement", "extrato", "payment", "pagamento",
        "transfer", "transferência", "infinitypay", "infinity pay", "bill", "fee", "charge",
        "email", "phone number", "endereço de email", "número de telefone", "change", "alterar", "update", "atualizar"
    ]
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
def topic_validator(state: CustomerSupportState) -> CustomerSupportState:
    """Validate if the query is related to InfinityPay banking services for Customer Support Agent."""
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
    banking_keywords = [
        "account", "transfer", "payment", "deposit", "withdrawal", "card", "bank",
        "money", "credit", "debit", "loan", "infinitypay", "infinity pay", "statement",
        "bill", "fee", "charge", "email", "phone number", "change", "update", "issue", "problem", "complain", "escalate",
        "conta", "transferência", "pagamento", "depósito", "saque", "cartão", "banco",
        "dinheiro", "crédito", "débito", "empréstimo", "extrato", "fatura", "taxa", "cobrança",
        "endereço de email", "número de telefone", "alterar", "atualizar", "problema", "reclamação", "escalar"
    ]
    off_topic_keywords = [
        "politics", "celebrity", "news", "weather", "sports", "movie",
        "política", "celebridade", "notícias", "tempo", "esporte", "filme",
        "election", "covid", "vaccine", "war"
    ]

    has_banking_context = any(keyword in current_query for keyword in banking_keywords)
    has_off_topic = any(keyword in current_query for keyword in off_topic_keywords)

    if has_off_topic and not has_banking_context:
        rejection_message = AIMessage(content="""
            Desculpe, sou um assistente especializado apenas em questões do InfinityPay.
            Como posso ajudá-lo com sua conta ou serviços bancários hoje?
            Posso ajudar com:
            • Informações da conta
            • Suporte técnico bancário
            • Outras consultas bancárias (não relacionadas a saldo/transações diretas)
            """) if state.get("language", "en") == "pt" else AIMessage(content="""
            I'm sorry, I'm a specialized assistant for InfinityPay banking services only.
            How can I help you with your account or banking needs today?
            I can help with:
            • Account information
            • Banking technical support
            • Other banking inquiries (not direct balance/transaction queries)
            """)
        return {**state, "messages": [rejection_message], "escalation_needed": False}
    return state

# Node: Main Customer Support Agent LLM Interaction
def customer_support_agent_node(state: CustomerSupportState) -> CustomerSupportState:
    """Main customer support agent node with LLM and tools."""
    system_prompt_content = load_prompt_template("customer_support", state.get("language", "en"))
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

def should_continue(state: CustomerSupportState) -> str:
    """Determine if we should continue to tools or end the Customer Support Agent graph."""
    last_message = state["messages"][-1]
    if (hasattr(last_message, 'content') and isinstance(last_message, AIMessage) and
        any(phrase in last_message.content for phrase in [
            "specialized assistant for InfinityPay",
            "assistente especializado apenas em questões do InfinityPay",
            "for security reasons",
            "por motivos de segurança"
        ])):
        return "end"
    if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        return "tools"
    return "end"  

# Node: Escalation Check
def escalation_check(state: CustomerSupportState) -> CustomerSupportState:
    """Check if escalation is needed based on conversation and keywords."""
    last_message = state["messages"][-1]
    escalation_keywords = [
        "complaint", "angry", "frustrated", "lawsuit", "legal",
        "reclamação", "raiva", "irritado", "processo", "jurídico",
        "need to change", "preciso alterar", "cannot update", "não consigo atualizar", "problem with"
    ]
    escalation_needed = any(keyword in last_message.content.lower() for keyword in escalation_keywords)
    return {**state, "escalation_needed": escalation_needed}

# Function to build and compile the Customer Support Agent graph
def build_customer_support_graph() -> StateGraph:
    """Build the customer support graph with proper LangGraph structure."""
    workflow = StateGraph(CustomerSupportState)

    # Add nodes to the workflow
    workflow.add_node("language_detector", language_detector)
    workflow.add_node("user_access_validator", user_access_validator)
    workflow.add_node("topic_validator", topic_validator)
    workflow.add_node("customer_support", customer_support_agent_node)
    workflow.add_node("tools", ToolNode(tools)) # ToolNode automatically executes tools
    workflow.add_node("escalation_check", escalation_check)

    # Define the entry point
    workflow.set_entry_point("language_detector")

    # Define edges
    workflow.add_edge("language_detector", "user_access_validator")
    workflow.add_edge("user_access_validator", "topic_validator")

    # Conditional edge from topic_validator
    workflow.add_conditional_edges(
        "topic_validator",
        lambda state: "escalation_check" if (
            hasattr(state["messages"][-1], 'content') and
            isinstance(state["messages"][-1], AIMessage) and
            any(phrase in state["messages"][-1].content for phrase in [
                "specialized assistant for InfinityPay", "assistente especializado apenas em questões do InfinityPay",
                "for security reasons", "por motivos de segurança"
            ])
        ) else "customer_support",
        {"customer_support": "customer_support", "escalation_check": "escalation_check"}
    )

    # Conditional edge from customer_support
    workflow.add_conditional_edges("customer_support", should_continue, {"tools": "tools", "end": "escalation_check"})
    workflow.add_edge("tools", "customer_support") 
    workflow.add_edge("escalation_check", END)  

    return workflow.compile()
