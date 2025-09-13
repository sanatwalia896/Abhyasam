import os
from langchain_groq import ChatGroq
from langchain_pinecone import PineconeVectorStore
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_community.chat_message_histories import ChatMessageHistory
from dotenv import load_dotenv
import logging
from typing import Dict
import os
import logging
from typing import Dict
from dotenv import load_dotenv
from pinecone import Pinecone
from langchain_groq import ChatGroq



logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

class RevisionAIChat:
    """Langchain-based chatbot for RevisionAI question-answering mode."""


    def __init__(self, model_name: str = "openai/gpt-oss-20b", index_name: str = "revisionai-index", namespace: str = "revisionai"):
        """
        Initialize the chatbot with Groq LLM, Pinecone RAG, and memory.
        
        Args:
            model_name (str): Groq model (e.g., 'llama3-8b-8192' or 'mixtral-8x7b-32768').
            
        """
        self.store={}
        # Embeddings (match Pinecone dimension)
        embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
        
        # Vector store for RAG
        self.vectorstore = PineconeVectorStore.from_existing_index(
            index_name=index_name,
            embedding=embeddings,
            namespace=namespace,
            text_key="text"
        )
        self.retriever=self.vectorstore.as_retriever(search_type="similarity_score_threshold",search_kwargs={"score_threshold":0.8})
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a helpful AI assistant."),
            MessagesPlaceholder(variable_name="history"),
            ("human", "{question}")
        ])
        
        # Groq LLM
        llm = ChatGroq(model=model_name, groq_api_key=os.getenv("GROQ_API_KEY"))
        self.retrieval_chain = (
        {"context": self.retriever, "question": lambda x: x["question"], "history": lambda x: x["history"]}
        | prompt
        | llm
        )
        
        self.chatbot=RunnableWithMessageHistory(
            self.retrieval_chain,
            self.get_session_history,
            input_messages_key='question',
            history_messages_key='history'
            
        )
        
        
    def get_session_history(self,session_id: str):
        if session_id not in self.store:
            self.store[session_id] = ChatMessageHistory()
        return self.store[session_id]
        
    def ask_question(self, question: str, session_id: str = "user1") -> Dict[str, str]:
        """
        Ask a question and get response with RAG and memory.
        
        Args:
            question (str): User's question.
        
        Returns:
            Dict with 'answer' and 'sources' (for transparency).
        """
        try:
            result = self.chatbot.invoke(
                {"question": question},
                config={"configurable": {"session_id": session_id}},
            )
            return {"answer": result.content}
        except Exception as e:
            logger.error(f"Error in chat: {e}")
            return {"answer": "Sorry, something went wrong. Try again!"}
        
# m=RevisionAIChat()
# question=input("Enter Your question")
# session_id='uder11'
# ans=m.ask_question(question=question,session_id=session_id)

# print("The answer is ,",ans['answer'])
        
            
        
       
