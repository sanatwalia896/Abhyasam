import os
import logging
import json
import re
from typing import Dict, List
from dotenv import load_dotenv
from pinecone import Pinecone
from langchain_groq import ChatGroq
from langchain_pinecone import PineconeVectorStore
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_huggingface import HuggingFaceEndpointEmbeddings
from langchain_core.output_parsers import JsonOutputParser

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

class AbhyasamChat:
    """Abhyasam AI: Chat + Quiz generation from Notion knowledge base with page-specific filtering."""

    def __init__(self, model_name: str = "openai/gpt-oss-20b"):
        self.store = {}
        self.index_name = "abhyasam-index"
        self.model_name = model_name  # Use a valid Groq model

        # Initialize HuggingFace embeddings
        self.hf_embeddings = HuggingFaceEndpointEmbeddings(
            model="sentence-transformers/all-mpnet-base-v2",
            task="feature-extraction",
            huggingfacehub_api_token=os.environ.get("HUGGINGFACE_TOKEN"),
        )

        # Initialize Pinecone
        pinecone_api_key = os.environ.get("PINECONE_API_KEY")
        pc = Pinecone(api_key=pinecone_api_key)
        self.index = pc.Index(self.index_name)
        self.vectorstore = PineconeVectorStore(index=self.index, embedding=self.hf_embeddings)

        # Base retriever (updated in methods to include page_title filter)
        self.retriever = self.vectorstore.as_retriever(
            search_type="mmr",
            search_kwargs={"k": 6, "lambda_mult": 0.25}
        )

        # Prompt for question answering
        self.base_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are Abhyasam AI. Answer student questions clearly based on the provided Notion context:\n{context}"),
            MessagesPlaceholder(variable_name="history"),
            ("human", "{question}")
        ])

        # Prompt for quiz generation (enforces MCQ format)
        self.quiz_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are Abhyasam AI, a teacher AI. Create only MCQ quizzes from the provided Notion context. "
                      "Each question must have 4 options (A, B, C, D) and specify the correct answer as a letter (A, B, C, or D). "
                      "Return the output as JSON: [{question: str, options: {A: str, B: str, C: str, D: str}, answer: str}]"),
            ("human", "Generate exactly {num_questions} MCQ questions from the following study material:\n\n{context}")
        ])

        # Initialize Groq LLM
        self.llm = ChatGroq(model=self.model_name, groq_api_key=os.getenv("GROQ_API_KEY"))

        # Retrieval chain for question answering
        self.retrieval_chain = (
            {
                "context": lambda x: "\n\n".join([doc.page_content for doc in self.retriever.invoke(x["question"], filter=x.get("filter", {"source": "Notion"}))]),
                "question": lambda x: x["question"],
                "history": lambda x: x["history"]
            }
            | self.base_prompt
            | self.llm
        )

        # Chatbot with history
        self.chatbot = RunnableWithMessageHistory(
            self.retrieval_chain,
            self.get_session_history,
            input_messages_key="question",
            history_messages_key="history"
        )

        # Quiz chain (no history)
        self.quiz_chain = (
            {"context": lambda x: x["context"], "num_questions": lambda x: x["num_questions"]}
            | self.quiz_prompt
            | self.llm
            | JsonOutputParser()
        )

    def get_session_history(self, session_id: str):
        if session_id not in self.store:
            self.store[session_id] = ChatMessageHistory()
        return self.store[session_id]

    def ask_question(self, question: str, session_id: str = "student1", page_title: str = None) -> Dict[str, str]:
        """Ask a question with optional page_title filter."""
        try:
            filter_dict = {"source": "Notion"}
            if page_title:
                filter_dict["page_title"] = page_title
                logger.info(f"Filtering by page_title: {page_title}")

            result = self.chatbot.invoke(
                {"question": question, "filter": filter_dict},
                config={"configurable": {"session_id": session_id}},
            )
            return {"answer": result.content}
        except Exception as e:
            logger.error(f"Error in chat: {e}")
            return {"answer": "⚠️ Something went wrong."}

    def generate_quiz(self, topic_query: str = "key concepts", num_batches: int = 3, questions_per_batch: int = 10, page_title: str = None) -> List[Dict]:
        """Generate MCQ quizzes for a specific page_title and dump to questions.json."""
        all_questions = []
        try:
            # Set filter for retriever
            filter_dict = {"source": "Notion"}
            if page_title:
                filter_dict["page_title"] = page_title
                logger.info(f"Generating quiz for page_title: {page_title}")

            # Retrieve context
            docs = self.retriever.invoke(topic_query, filter=filter_dict)
            context = "\n\n".join([doc.page_content for doc in docs])

            if not context:
                logger.warning("No context retrieved for quiz generation.")
                return []

            # Generate quizzes in batches
            for batch in range(num_batches):
                logger.info(f"Generating quiz batch {batch + 1}/{num_batches}")
                result = self.quiz_chain.invoke({
                    "context": context,
                    "num_questions": questions_per_batch
                })
                all_questions.extend(result)

            # Limit to 30 questions
            all_questions = all_questions[:30]

            # Validate and format questions
            formatted_questions = []
            for q in all_questions:
                if (
                    isinstance(q, dict) and
                    "question" in q and
                    "options" in q and
                    isinstance(q["options"], dict) and
                    all(k in q["options"] for k in ["A", "B", "C", "D"]) and
                    "answer" in q and
                    q["answer"] in ["A", "B", "C", "D"]
                ):
                    formatted_questions.append(q)
                else:
                    logger.warning(f"Invalid question format: {q}")

            # Dump to questions.json in static folder
            with open("static/questions.json", "w") as f:
                json.dump(formatted_questions, f, indent=2)
            logger.info(f"Dumped {len(formatted_questions)} questions to static/questions.json")

            return formatted_questions
        except Exception as e:
            logger.error(f"Error in quiz generation: {e}")
            return []

if __name__ == "__main__":
    chat = AbhyasamChat()
    # Example: Test with a specific page title
    response = chat.ask_question("What is the capital of France?", page_title="Geography Notes")
    print(response)
    quiz = chat.generate_quiz(page_title="Geography Notes")
    print(quiz)