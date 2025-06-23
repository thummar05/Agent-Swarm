import uuid
from typing import List, Dict, Any, Optional
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, BaseMessage
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware  

from core.state import OverallAgentState

from Agents.customer_support_agent import (
    build_customer_support_graph,
    map_to_customer_support_state
)
from Agents.knowledge_agent import (
    build_rag_agent,
    setup_knowledge_base,  
    map_to_knowledge_agent_state
)
from Agents.slack_agent import (
    build_slack_agent_graph,
    map_to_slack_agent_state
)

from Agents.router_agent import build_router_graph, route_agent 
from Agents.personality_agent import build_personality_graph, map_to_personality_state
from Agents.custom_agent import build_custom_agent_graph, map_to_custom_agent_state
from Agents.slack_agent import send_slack_notification
from utils.lang_detect import detect_language 

# Global instances of compiled sub-graphs
customer_support_app = None
knowledge_app = None
router_app = None
personality_app = None
custom_agent_app = None
slack_agent_app = None
global_vectorstore = None # This will now remain None until first use by KnowledgeAgent
overall_app = None # The main LangGraph application

 
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initializes agents on startup and cleans up on shutdown."""
    print("Initializing all agents for FastAPI. Please wait...")
    global customer_support_app, knowledge_app, router_app,slack_agent_app, personality_app, custom_agent_app, global_vectorstore, overall_app

    # Build sub-graphs
    customer_support_app = build_customer_support_graph()
    knowledge_app = build_rag_agent() 
    custom_agent_app = build_custom_agent_graph()
    router_app = build_router_graph()
    slack_agent_app = build_slack_agent_graph()
    personality_app = build_personality_graph()

    # Build the overall system graph
    overall_app = build_overall_system_graph()

    print("Agents initialized and overall system graph built.")
    yield
    print("Shutting down agents.")

app = FastAPI(title="InfinityPay AI Assistant API", version="1.0", lifespan=lifespan)

 
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   
    allow_credentials=True,
    allow_methods=["*"],   
    allow_headers=["*"],   
)


# Pydantic models for request and response
class QueryRequest(BaseModel):
    message: str
    user_id: str

class WorkflowStep(BaseModel):
    agent_name: str
    tool_calls: Dict[str, Any]

class QueryResponse(BaseModel):
    response: str
    source_agent_response: Optional[str] = None
    agent_workflow: List[Any]

# Define routing configuration at module level
ROUTING_CONFIG = {
    "customer_support": "CustomerSupportAgent",
    "knowledge_agent": "KnowledgeAgent",
    "custom_agent": "CustomAgent",
    "default": "PersonalityLayer"  
}

def route_agent_wrapper(state: OverallAgentState) -> OverallAgentState:
    """
    Wrapper for router agent to capture its decision and add to workflow trace.
    Calls the actual `route_agent` function.
    """
    print("\n--- Calling Router Agent ---")
    # The actual route_agent updates state["next_agent"] and state["language"]
    result_state = route_agent(state)

    # Capture router decision for logging and routing in the overall graph
    router_decision_key = result_state.get("next_agent", "default")
    decided_agent_name = ROUTING_CONFIG.get(router_decision_key, ROUTING_CONFIG["default"])

    # Add router workflow step
    result_state["workflow_trace"].append({
        "agent_name": "RouterAgent",
        "tool_calls": {
            "LLM_decision": decided_agent_name # More descriptive for router's output
        }
    })
    return result_state

def _extract_tool_calls_from_langgraph_result(agent_result_messages: List[BaseMessage]) -> Dict[str, Any]:
    """Extracts tool calls and their outputs from a list of LangGraph messages."""
    tool_calls_dict = {}
    last_ai_message_with_tools_index = -1

    # Find the last AI message that contains tool calls
    for i in range(len(agent_result_messages) - 1, -1, -1):
        msg = agent_result_messages[i]
        if isinstance(msg, AIMessage) and hasattr(msg, 'tool_calls') and msg.tool_calls:
            last_ai_message_with_tools_index = i
            break

    if last_ai_message_with_tools_index != -1:
        last_ai_message_with_tools = agent_result_messages[last_ai_message_with_tools_index]
        for tool_call in last_ai_message_with_tools.tool_calls:
            tool_name = tool_call.get('name')
            tool_id = tool_call.get('id')
            tool_output = None
            # Find the corresponding ToolMessage for the tool_call_id
            for j in range(last_ai_message_with_tools_index + 1, len(agent_result_messages)):
                response_msg = agent_result_messages[j]
                if isinstance(response_msg, ToolMessage) and response_msg.tool_call_id == tool_id:
                    tool_output = response_msg.content
                    break
            tool_calls_dict[tool_name] = tool_output if tool_output is not None else "Output not captured or tool failed."
    return tool_calls_dict


# Wrapper functions for sub-agent execution
def call_customer_support_executor(state: OverallAgentState) -> OverallAgentState:
    print("\n--- Calling Customer Support Agent ---")
    cs_input_state = map_to_customer_support_state(state)
    config = {"configurable": {"thread_id": state["session_user_id"]}}
    cs_result = customer_support_app.invoke(cs_input_state, config)

    # Append valid messages from sub-agent result to overall state messages
    state["messages"].extend([msg for msg in cs_result["messages"] if isinstance(msg, BaseMessage)])

    state["tools_used"].extend(cs_result.get("tools_used", []))
    state["escalation_needed"] = cs_result.get("escalation_needed", False)

    last_cs_message = next((msg.content for msg in reversed(cs_result["messages"]) if isinstance(msg, AIMessage)), "")
    state["raw_agent_output"] = last_cs_message

    # Extract tool calls and their outputs for workflow trace
    tool_calls_dict = _extract_tool_calls_from_langgraph_result(cs_result["messages"])
    state["workflow_trace"].append({"agent_name": "CustomerSupportAgent", "tool_calls": tool_calls_dict})
    return state

def call_knowledge_agent_executor(state: OverallAgentState) -> OverallAgentState:
    print("\n--- Calling Knowledge Agent ---")
    kg_input_state = map_to_knowledge_agent_state(state)
    kg_result = knowledge_app.invoke(kg_input_state)

    answer_from_kg = kg_result.get("answer", "No answer found by Knowledge Agent.")
    state["messages"].append(AIMessage(content=answer_from_kg))
    state["raw_agent_output"] = answer_from_kg

    # KnowledgeAgent returns 'actual_tool_outputs' directly
    actual_tool_outputs = kg_result.get("actual_tool_outputs", {})
    state["workflow_trace"].append({"agent_name": "KnowledgeAgent", "tool_calls": actual_tool_outputs})
    return state

def call_custom_agent_executor(state: OverallAgentState) -> OverallAgentState:
    print("\n--- Calling Custom Agent ---")
    custom_input_state = map_to_custom_agent_state(state)
    config = {"configurable": {"thread_id": state["session_user_id"]}}
    custom_result = custom_agent_app.invoke(custom_input_state, config)

    # Append valid messages from sub-agent result to overall state messages
    state["messages"].extend([msg for msg in custom_result["messages"] if isinstance(msg, BaseMessage)])

    state["tools_used"].extend(custom_result.get("tools_used", []))
    last_custom_message = next((msg.content for msg in reversed(custom_result["messages"]) if isinstance(msg, AIMessage)), "")
    state["raw_agent_output"] = last_custom_message

    # Extract tool calls and their outputs for workflow trace
    tool_calls_dict = _extract_tool_calls_from_langgraph_result(custom_result["messages"])
    state["workflow_trace"].append({"agent_name": "CustomAgent", "tool_calls": tool_calls_dict})
    return state

def call_slack_agent_executor(state: OverallAgentState) -> OverallAgentState:
    print("\n--- Calling Slack Agent for Suspicious Query ---")
    slack_input_state = map_to_slack_agent_state(state)
    slack_result = slack_agent_app.invoke(slack_input_state)

    # Append valid messages from sub-agent result to overall state messages
    state["messages"].extend([msg for msg in slack_result["messages"] if isinstance(msg, BaseMessage)])

    state["tools_used"].extend(slack_result.get("tools_used", []))
    last_slack_message = next((msg.content for msg in reversed(slack_result["messages"]) if isinstance(msg, AIMessage)), "")
    state["raw_agent_output"] = last_slack_message

    # Extract tool calls and their outputs for workflow trace
    tool_calls_dict = _extract_tool_calls_from_langgraph_result(slack_result["messages"])
    state["workflow_trace"].append({"agent_name": "SlackAgent", "tool_calls": tool_calls_dict})

    # Send notification to Slack channel if needed
    if slack_result.get("send_notification", False):
        send_slack_notification(state["session_user_id"], last_slack_message)

    return state

def call_personality_layer_executor(state: OverallAgentState) -> OverallAgentState:
    print("\n--- Applying Personality Layer ---")
    personality_input_state = map_to_personality_state(state)
    personality_result = personality_app.invoke(personality_input_state)

    final_response_content = personality_result.get("final_response", "Error applying personality.")
    state["final_response"] = final_response_content

    # Replace the last AI message (raw output) with the personality-enhanced message
    if state["messages"] and isinstance(state["messages"][-1], AIMessage):
        state["messages"].pop() # Remove raw AI response from previous agent
    state["messages"].append(AIMessage(content=final_response_content))

    state["workflow_trace"].append({
        "agent_name": "PersonalityLayer",
        "tool_calls": {"LLM": final_response_content}
    })
    return state

def build_overall_system_graph() -> StateGraph:
    """Builds the main LangGraph for the overall system, orchestrating sub-agents."""
    workflow = StateGraph(OverallAgentState)

    # Add nodes representing the router and each agent executor
    workflow.add_node("router", route_agent_wrapper)
    workflow.add_node("customer_support_executor", call_customer_support_executor)
    workflow.add_node("knowledge_agent_executor", call_knowledge_agent_executor)
    workflow.add_node("custom_agent_executor", call_custom_agent_executor)
    workflow.add_node("slack_agent_executor", call_slack_agent_executor)  
    workflow.add_node("personality_layer", call_personality_layer_executor)

    # Set the entry point of the overall graph
    workflow.set_entry_point("router")

    # Define conditional edges from the router to direct to the appropriate agent executor
    workflow.add_conditional_edges(
        "router",
        lambda state: state["next_agent"], # Uses the 'next_agent' set by the router
        {
            "customer_support": "customer_support_executor",
            "knowledge_agent": "knowledge_agent_executor",
            "custom_agent": "custom_agent_executor",
            "slack_agent": "slack_agent_executor",  
            "default": "personality_layer" # Fallback if no specific agent is chosen
        }
    )

    # Define edges from each agent executor to the personality layer
    workflow.add_edge("customer_support_executor", "personality_layer")
    workflow.add_edge("knowledge_agent_executor", "personality_layer")
    workflow.add_edge("custom_agent_executor", "personality_layer")
    workflow.add_edge("slack_agent_executor", "personality_layer")

    # Define the final edge from the personality layer to the end of the graph
    workflow.add_edge("personality_layer", END)

    # Configure memory for the graph (important for conversational history)
    memory = MemorySaver()
    return workflow.compile(checkpointer=memory)

@app.post("/process_query", response_model=QueryResponse)
async def process_query_endpoint(request: QueryRequest):
    """
    Processes a user query through the InfinityPay Agent Swarm and returns a structured response.
    """
    global overall_app
    if overall_app is None: # Check if app is initialized (should be by lifespan)
        raise HTTPException(status_code=503, detail="Agent system not initialized yet. Please wait a moment.")

    print(f"\nReceived query for user '{request.user_id}': '{request.message}'")

    session_user_id = request.user_id
    user_query = request.message

    # Initialize the overall state for the LangGraph
    initial_overall_state = OverallAgentState(
        messages=[HumanMessage(content=user_query)],
        session_user_id=session_user_id,
        current_query_user_id=None,  
        language=detect_language(user_query),  
        tools_used=[],
        escalation_needed=False,
        user_data=None,  
        current_query=user_query,
        access_denied=False, 
        next_agent=None,  
        question=user_query,  
        answer="", 
        raw_agent_output=None,  
        final_response=None, 
        workflow_trace=[] 
    )

    # Configuration for LangGraph (thread_id for memory)
    config = {"configurable": {"thread_id": session_user_id}}

    try:
        # Invoke the overall LangGraph with the initial state
        final_state = await overall_app.ainvoke(initial_overall_state, config) # Use ainvoke for FastAPI async

        # Extract results from the final state
        final_response_content = final_state.get("final_response")
        source_agent_output = final_state.get("raw_agent_output")

        # Fallback for final_response_content if PersonalityLayer didn't explicitly set it
        if not final_response_content:
            final_response_content = next((msg.content for msg in reversed(final_state["messages"]) if isinstance(msg, AIMessage)), "No response generated.")

        # Format agent workflow for the API response
        agent_workflow_list = []
        for step in final_state["workflow_trace"]:
            agent_name = step["agent_name"]
            tool_calls = step.get("tool_calls", {})
            # Removed the special handling for KnowledgeAgent's trace format
            # All steps will now be appended as single dictionaries for consistency
            agent_workflow_list.append({"agent_name": agent_name, "tool_calls": tool_calls})

        return QueryResponse(
            response=final_response_content,
            source_agent_response=source_agent_output,
            agent_workflow=agent_workflow_list
        )

    except Exception as e:
        print(f"An error occurred during agent processing: {e}")
        import traceback
        traceback.print_exc() # Print full traceback for debugging
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
    
@app.get("/ping")
def ping():
    return {"status": "alive"}
