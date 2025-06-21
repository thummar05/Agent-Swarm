import requests
from bs4 import BeautifulSoup
from typing import TypedDict, List, Dict, Any
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain.chains import RetrievalQA
from langgraph.graph import StateGraph, START, END
from langchain_core.tools import tool
from dotenv import load_dotenv
from langchain_community.tools import DuckDuckGoSearchRun
import sys
import os

# Adjust sys.path for project root if necessary
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.state import OverallAgentState
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, AIMessage
import uuid
from utils.load_prompt import load_prompt_template

load_dotenv()

# Define the state specific to the Knowledge Agent
class KnowledgeAgentState(TypedDict):
    question: str
    answer: str
    language: str
    actual_tool_outputs: Dict[str, Any]

# Define path for FAISS index persistence
FAISS_INDEX_PATH = "faiss_index_infinitepay"

# Web Scraping function
def scrape_websites(urls: list) -> str:
    """Scrapes content from a list of URLs."""
    all_content = ""
    for url in urls:
        print(f"Scraping: {url}") 
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            for script in soup(["script", "style"]):
                script.decompose()
            content = soup.get_text(separator=' ', strip=True)
            if content:
                all_content += content + "\n\n"
        except requests.RequestException as e:
            print(f"Error scraping website {url}: {e}")
        except Exception as e:
            print(f"Unexpected error while parsing {url}: {e}")
    return all_content

# Create and/or load vector store
def create_or_load_vectorstore() -> FAISS:
    """
    Loads FAISS vector store from disk if it exists, otherwise creates it
    by scraping websites and then saves it to disk.
    """
    embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")

    if os.path.exists(FAISS_INDEX_PATH):
        print(f"Loading knowledge base from disk: {FAISS_INDEX_PATH}")
        try:
            vectorstore = FAISS.load_local(FAISS_INDEX_PATH, embeddings, allow_dangerous_deserialization=True)
            print("Knowledge base loaded successfully from disk!")
            return vectorstore
        except Exception as e:
            print(f"Error loading FAISS index from disk: {e}. Attempting to rebuild.")
            # Fallback to rebuild if loading fails
            return _build_and_save_vectorstore(embeddings)
    else:
        print("Knowledge base not found on disk. Building from scratch...")
        return _build_and_save_vectorstore(embeddings)

def _build_and_save_vectorstore(embeddings: GoogleGenerativeAIEmbeddings) -> FAISS:
    """Helper to build vectorstore from scratch and save it."""
    urls = [
        "https://www.infinitepay.io",
        "https://www.infinitepay.io/maquininha",
        "https://www.infinitepay.io/maquininha-celular",
        "https://www.infinitepay.io/tap-to-pay",
        "https://www.infinitepay.io/pdv",
        "https://www.infinitepay.io/receba-na-hora",
        "https://www.infinitepay.io/gestao-de-cobranca-2",
        "https://www.infinitepay.io/gestao-de-cobranca",
        "https://www.infinitepay.io/link-de-pagamento",
        "https://www.infinitepay.io/loja-online",
        "https://www.infinitepay.io/boleto",
        "https://www.infinitepay.io/conta-digital",
        "https://www.infinitepay.io/conta-pj",
        "https://www.infinitepay.io/pix",
        "https://www.infinitepay.io/pix-parcelado",
        "https://www.infinitepay.io/emprestimo",
        "https://www.infinitepay.io/cartao",
        "https://www.infinitepay.io/rendimento"
    ]
    scraped_content = scrape_websites(urls)

    if not scraped_content:
        print("Warning: No content scraped. Vector store will not be created.")
        return None

    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    docs = splitter.create_documents([scraped_content])
    print(f"Created {len(docs)} document chunks for embedding.")

    try:
        vectorstore = FAISS.from_documents(docs, embeddings)
        vectorstore.save_local(FAISS_INDEX_PATH)
        print("Knowledge base built and saved successfully to disk!")
        return vectorstore
    except Exception as e:
        print(f"Error building or saving vector store: {e}")
        return None

# Global vectorstore instance  
_vectorstore = None

def setup_knowledge_base():
    """Sets up the global knowledge base vectorstore (loads from disk or builds)."""
    global _vectorstore
    if _vectorstore is None:
        _vectorstore = create_or_load_vectorstore()
        if _vectorstore:
            print("Global vectorstore ready.")
        else:
            print("Failed to initialize global vectorstore.")
    return _vectorstore

# Helper function to map OverallAgentState to KnowledgeAgentState
def map_to_knowledge_agent_state(state: OverallAgentState) -> KnowledgeAgentState:
    """Maps the overall agent state to the KnowledgeAgent's specific state."""
    return KnowledgeAgentState(
        question=state["current_query"],
        answer="",
        language=state["language"],
        actual_tool_outputs={}
    )

# Initialize LLM for RAG and tool binding
llm_rag = ChatGoogleGenerativeAI(model="gemini-1.5-flash", temperature=0.2)

@tool
def retrieve_knowledge(question: str) -> str:
    """
    Retrieves relevant information from the indexed knowledge base based on the question.
    Use this tool for general information about InfinityPay products, services, policies, and FAQs.
    Do NOT use this for specific user account information like balance or transactions.
    """
    global _vectorstore
    if _vectorstore is None:
        setup_knowledge_base() # Attempt to initialize if not already
        if _vectorstore is None:
            return "Knowledge base not initialized. Cannot retrieve information."
    try:
         
        retriever = _vectorstore.as_retriever(search_kwargs={"k": 5})
        qa_chain = RetrievalQA.from_chain_type(
            llm=llm_rag,
            chain_type="stuff",
            retriever=retriever,
            return_source_documents=True
        )
        response = qa_chain.invoke({"query": question})
        result = response.get("result", "No relevant information found in the knowledge base.")
         
        return result
    except Exception as e:
        print(f"retrieve_knowledge: Error retrieving from knowledge base: {str(e)}")
        return f"Error retrieving from knowledge base: {str(e)}"

@tool
def web_search(query: str) -> str:
    """
    Performs a general web search to find information. Use this tool for questions that are not
    directly about InfinityPay's internal products, services, or FAQs, but are related to
    broader banking, financial industry trends, or general knowledge.
    Args:
        query: The search query.
    Returns:
        A string containing relevant snippets from the web search results.
    """
    try:
        search_tool = DuckDuckGoSearchRun()
        result = search_tool.run(query)
        return result
    except Exception as e:
        print(f"web_search: Search tool error: {str(e)}")
        return f"Search error: {str(e)}"

# Define tools for the Knowledge Agent
knowledge_tools = [retrieve_knowledge, web_search]
llm_rag_with_tools = llm_rag.bind_tools(knowledge_tools)

def knowledge_agent_node(state: KnowledgeAgentState) -> KnowledgeAgentState:
    """
    The main node for the Knowledge Agent, processing questions and retrieving answers.
    It decides whether to use the internal knowledge base or perform a web search.
    """
    current_question = state["question"]
    current_language = state.get("language", "en")

    # Load system prompt for the LLM
    try:
        system_prompt_content = load_prompt_template("knowledge_agent", current_language)
    except Exception as e:
        print(f"Error loading prompt template for Knowledge Agent: {e}")
        system_prompt_content = ("You are an assistant specialized in InfinityPay. "
                                 "Use the available tools to answer questions about InfinityPay products and services. "
                                 "Always try to use the retrieve_knowledge tool first for questions related to InfinityPay products." if current_language == 'en' else
                                 "Você é um assistente especializado em InfinityPay. Use as ferramentas disponíveis para responder perguntas sobre produtos e serviços da InfinityPay. Sempre tente usar a ferramenta retrieve_knowledge primeiro para perguntas relacionadas aos produtos da InfinityPay.")

    messages_for_llm_decision = [
        SystemMessage(content=system_prompt_content),
        HumanMessage(content=current_question)
    ]

    response_from_llm_with_tools = llm_rag_with_tools.invoke(messages_for_llm_decision)

    final_answer = ""
    actual_tool_outputs = {}

    if hasattr(response_from_llm_with_tools, 'tool_calls') and response_from_llm_with_tools.tool_calls:
        messages_with_tool_call = list(messages_for_llm_decision)
        messages_with_tool_call.append(response_from_llm_with_tools)

        for tool_call in response_from_llm_with_tools.tool_calls:
            tool_call_id = tool_call.get('id') or str(uuid.uuid4())
            tool_name = tool_call.get('name')
            tool_args = tool_call.get('args', {})

            try:
                output = None
                if tool_name == 'retrieve_knowledge':
                    output = retrieve_knowledge.invoke(tool_args)
                    actual_tool_outputs['retrieve_knowledge'] = output
                elif tool_name == 'web_search':
                    output = web_search.invoke(tool_args)
                    actual_tool_outputs['web_search'] = output
                else:
                    output = f"Unknown tool: {tool_name}"
                    print(f"Knowledge Agent: Encountered unknown tool '{tool_name}'")

                messages_with_tool_call.append(ToolMessage(content=output, tool_call_id=tool_call_id, name=tool_name))

            except Exception as e:
                error_output = f"Error executing tool {tool_name}: {str(e)}"
                messages_with_tool_call.append(ToolMessage(content=error_output, tool_call_id=tool_call_id, name=tool_name))
                print(f"Knowledge Agent: Error executing tool '{tool_name}': {e}")

        # Invoke LLM again with the full history including tool outputs to get a refined answer
        final_answer_response = llm_rag.invoke(messages_with_tool_call)
        final_answer = final_answer_response.content

    else:
        # If no tool calls, first try retrieve_knowledge for InfinityPay related questions
        infinitypay_keywords = ['phone', 'card machine', 'maquininha', 'celular', 'tap to pay', 'infinitypay',
                                'payment', 'pagamento', 'pos', 'terminal', 'mobile', 'app']
        is_infinitypay_related = any(keyword.lower() in current_question.lower() for keyword in infinitypay_keywords)

        if is_infinitypay_related:
            try:
                knowledge_output = retrieve_knowledge.invoke({"question": current_question})
                actual_tool_outputs['retrieve_knowledge'] = knowledge_output
                # Synthesize answer from knowledge base output
                synthesis_prompt = (f"Based on the following information from the knowledge base, answer the user's question:\n\n"
                                    f"Question: {current_question}\n\n"
                                    f"Knowledge base information:\n{knowledge_output}\n\n"
                                    f"Please provide a helpful and informative answer:")
                final_answer_response = llm_rag.invoke([HumanMessage(content=synthesis_prompt)])
                final_answer = final_answer_response.content
            except Exception as e:
                print(f"Knowledge Agent: Error in forced retrieve_knowledge: {e}")
                final_answer = response_from_llm_with_tools.content
        else:
            final_answer = response_from_llm_with_tools.content

    # Check if answer is insufficient and try web search fallback if not already used
    insufficient_indicators = [
        "I don't know", "I cannot find", "not provided", "não sei", "não posso encontrar",
        "não fornecido", "based on the provided context, I cannot",
        "com base no contexto fornecido, não posso", "no answer found",
        "cannot retrieve information", "search error"
    ]

    is_insufficient = (
        not final_answer or
        len(final_answer.strip()) < 20 or
        any(indicator.lower() in final_answer.lower() for indicator in insufficient_indicators)
    )

    if is_insufficient and 'web_search' not in actual_tool_outputs:
        try:
            fallback_search_result = web_search.invoke({"query": current_question})

            if fallback_search_result and len(fallback_search_result.strip()) > 10 and "Search error" not in fallback_search_result.lower():
                search_prompt = (f"Com base nas seguintes informações de pesquisa, responda a pergunta em português de forma clara e útil:\n\n"
                                 f"Pergunta: {current_question}\n\n"
                                 f"Informações da pesquisa:\n{fallback_search_result}\n\n"
                                 f"Resposta em português:") if current_language == 'pt' else (
                                 f"Based on the following search information, answer the question clearly and helpfully:\n\n"
                                 f"Question: {current_question}\n\n"
                                 f"Search information:\n{fallback_search_result}\n\n"
                                 f"Answer:")

                processed_answer = llm_rag.invoke([HumanMessage(content=search_prompt)])
                final_answer = processed_answer.content
                actual_tool_outputs['web_search'] = fallback_search_result
            else:
                final_answer = "Desculpe, não consegui encontrar informações relevantes." if current_language == 'pt' else "Sorry, I couldn't find relevant information."

        except Exception as search_error:
            print(f"Knowledge Agent: Error during fallback web search: {search_error}")
            final_answer = "Erro ao buscar informações adicionais." if current_language == 'pt' else "Error searching for additional information."

    return {
        "question": current_question,
        "answer": final_answer,
        "language": current_language,
        "actual_tool_outputs": actual_tool_outputs
    }

def build_rag_agent(vectorstore=None) -> StateGraph:
    """
    Builds the RAG (Knowledge) agent graph.
    The vectorstore parameter is kept for compatibility but not directly used within this
    function as the global _vectorstore handles the state.
    """
    workflow = StateGraph(KnowledgeAgentState)
    workflow.add_node("RAG_QA", knowledge_agent_node)
    workflow.set_entry_point("RAG_QA")
    workflow.add_edge("RAG_QA", END)
    return workflow.compile()
