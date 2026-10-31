import os
import logging
import json
import random
from typing import Dict, List
from dotenv import load_dotenv
from pinecone import Pinecone
from langchain_groq import ChatGroq
from langchain_pinecone import PineconeVectorStore
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_community.chat_message_histories import ChatMessageHistory
from embedding_adapter import FastEmbedLangChainAdapter
from cloud_artifacts import load_session, save_session
from langchain_core.documents import Document
from langchain_core.messages import messages_to_dict, messages_from_dict
from json_output import parse_json_response
from groq_pacing import PacedGroq

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

class AbhyasamChat:
    """Abhyasam AI: Chat and quiz generation from Notion knowledge base with page-specific filtering."""

    def __init__(self, model_name: str | None = None):
        self.store = {}
        self.index_name = os.getenv("PINECONE_INDEX_NAME", "abhyasam-fastembed-index")
        self.model_name = model_name or os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
        self.namespace = os.getenv("PINECONE_NAMESPACE", "notion-knowledge")

        # Use the same 384-dimensional model used during ingestion.
        self.hf_embeddings = FastEmbedLangChainAdapter()

        # Initialize Pinecone
        pinecone_api_key = os.environ.get("PINECONE_API_KEY")
        pc = Pinecone(api_key=pinecone_api_key)
        self.index = pc.Index(self.index_name)
        self.vectorstore = PineconeVectorStore(
            index=self.index,
            embedding=self.hf_embeddings,
            namespace=self.namespace,
        )


        # Prompt for question answering
        self.base_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are Abhyasam AI. Answer student questions clearly based on the provided Notion context:\n{context}"),
            MessagesPlaceholder(variable_name="history"),
            ("human", "{question}")
        ])


        # Prompt for Flashcards generation (escaped curly braces in JSON example)
        self.flashcard_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are Abhyasam AI, a teacher AI. Create flashcards from the provided Notion context. "
                      "Each flashcard must have a 'front' (concept or question) and a 'back' (definition or answer). "
                      'Return ONLY valid JSON: {{"flashcards":[{{"front":"question","back":"answer"}}]}}'),
            ("human", "Generate exactly {num_flashcards} flashcards from the following study material:\n\n{context}")
        ])

        # Prompt for generating a single open-ended question
        self.generate_question_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a teacher AI. Generate one clear, open-ended question to test understanding from the provided Notion context. Just output the question."),
            ("human", "{context}")
        ])

        # Prompt for evaluating user's answer (escaped curly braces in JSON)
        self.evaluate_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a teacher AI. Evaluate the student's answer based on the question and Notion context. "
                      'Return ONLY valid JSON: {{"score": 8, "feedback": "Explain the evaluation here"}}'),
            ("human", "Question: {question}\nStudent Answer: {answer}\nContext: {context}")
        ])

        # Initialize Groq LLM
        self.llm = PacedGroq(ChatGroq(
            model=self.model_name, groq_api_key=os.getenv("GROQ_API_KEY"),
            max_retries=0, timeout=90, max_tokens=2048,
            reasoning_effort="low" if self.model_name.startswith("openai/gpt-oss") else None,
        ))

        # Retrieval chain for question answering
        self.retrieval_chain = (
            {
                "context": lambda x: "\n\n".join([
                    doc.page_content
                    for doc in self._retrieve(
                        x["question"],
                        x.get("filter", {"source": "Notion"}),
                    )
                ]),
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



    def get_session_history(self, session_id: str) -> ChatMessageHistory:
        """Retrieve or create session history for chat."""
        saved = load_session("chat", session_id)
        self.store[session_id] = ChatMessageHistory(messages=messages_from_dict(saved["messages"]) if saved else [])
        return self.store[session_id]

    def _retrieve(self, query: str, filter_dict: dict, k: int = 8):
        """Use the vector store directly so Pinecone receives the filter."""
        documents = self.vectorstore.similarity_search(
            query,
            k=k,
            filter=filter_dict,
            namespace=self.namespace,
        )
        logger.info(
            "Pinecone retrieval: index=%s namespace=%s filter=%s documents=%d",
            self.index_name,
            self.namespace,
            filter_dict,
            len(documents),
        )
        return documents

    @staticmethod
    def _parse_json(content: str):
        return parse_json_response(content)

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
            save_session("chat", session_id, {"messages": messages_to_dict(self.store[session_id].messages[-40:])})
            return {"answer": result.content}
        except Exception as e:
            logger.error(f"Error in chat: {e}")
            raise

    def generate_quiz(self, topic_query="key concepts", num_batches=1, questions_per_batch=10, page_title=None):
        """Compatibility entry point for MCQ generation."""
        from mcq_service import MCQService
        return MCQService(self).generate(topic_query, num_batches * questions_per_batch, page_title)


    def generate_flashcards(self, topic_query: str = "key concepts", num_batches: int = 2, flashcards_per_batch: int = 5, page_title: str = None) -> List[Dict]:
        """Generate flashcards for a specific page_title and return them."""
        all_flashcards = []
        try:
            filter_dict = {"source": "Notion"}
            if page_title:
                filter_dict["page_title"] = page_title
                logger.info(f"Generating flashcards for page_title: {page_title}")

            docs = self._retrieve(topic_query, filter_dict, k=12)
            context = "\n\n".join([doc.page_content for doc in docs])

            if not context:
                raise RuntimeError(
                    f"No context retrieved from Pinecone index "
                    f"'{self.index_name}' namespace '{self.namespace}'. "
                    "Check that ingestion used the same index and namespace."
                )

            for batch in range(num_batches):
                logger.info(f"Generating flashcards batch {batch + 1}/{num_batches}")
                response = self.llm.bind(response_format={"type": "json_object"}).invoke(
                    self.flashcard_prompt.format_messages(
                        context=context,
                        num_flashcards=flashcards_per_batch,
                    )
                )
                result = self._parse_json(response.content)
                if isinstance(result, dict):
                    result = result.get("flashcards", result.get("cards", []))
                all_flashcards.extend(result)

            all_flashcards = all_flashcards[:20]

            formatted_flashcards = []
            for f in all_flashcards:
                if (
                    isinstance(f, dict) and
                    "front" in f and
                    "back" in f and
                    isinstance(f["front"], str) and bool(f["front"].strip()) and
                    isinstance(f["back"], str) and bool(f["back"].strip())
                ):
                    formatted_flashcards.append(f)
                else:
                    logger.warning(f"Invalid flashcard format: {f}")


            return formatted_flashcards
        except Exception as e:
            logger.error(f"Error in flashcard generation: {e}")
            raise

    def start_interactive_quiz(self, session_id: str, num_questions: int, page_title: str = None) -> Dict[str, str]:
        """Initialize an interactive quiz session with specified number of questions."""
        try:
            if num_questions < 1:
                logger.warning("Number of questions must be at least 1.")
                return {"status": "error", "message": "Number of questions must be at least 1."}

            filter_dict = {"source": "Notion"}
            if page_title:
                filter_dict["page_title"] = page_title
                logger.info(f"Quiz filtered by page_title: {page_title}")

            # Fetch diverse documents for quiz
            docs = self._retrieve(
                "generate diverse quiz questions",
                filter_dict,
                k=max(20, num_questions * 2),
            )

            if len(docs) < num_questions:
                logger.warning(f"Not enough content retrieved: {len(docs)} chunks.")
                return {"status": "error", "message": f"Not enough content for {num_questions} questions."}

            # Shuffle and select
            random.shuffle(docs)
            selected_docs = docs[:num_questions]

            # Store quiz state
            self.store[session_id + "_quiz"] = {
                "docs": selected_docs,
                "current_question": 0,
                "scores": [],
                "questions": [],
                "page_title": page_title
            }

            # Generate first question
            question = self._generate_single_question(selected_docs[0].page_content)
            self.store[session_id + "_quiz"]["questions"].append(question)
            self._save_practice(session_id, self.store[session_id + "_quiz"])

            return {
                "status": "success",
                "question": question,
                "question_number": 1,
                "total_questions": num_questions
            }
        except Exception as e:
            logger.error(f"Error starting quiz: {e}")
            raise

    def _save_practice(self, session_id, state):
        save_session("short-answer", session_id, {
            **state,
            "docs": [{"page_content": doc.page_content, "metadata": doc.metadata} for doc in state["docs"]],
        })

    def _generate_single_question(self, context: str) -> str:
        """Generate a single open-ended question from context."""
        question_chain = self.generate_question_prompt | self.llm
        return question_chain.invoke({"context": context}).content.strip()

    def submit_quiz_answer(self, session_id: str, answer: str) -> Dict[str, any]:
        """Evaluate user's answer and return feedback or next question."""
        try:
            quiz_state = load_session("short-answer", session_id)
            if not quiz_state:
                return {"status": "error", "message": "No active quiz session."}
            if quiz_state.get("complete"):
                return {"status": "error", "message": "This practice is complete. Start a new session."}
            quiz_state["docs"] = [Document(**doc) for doc in quiz_state["docs"]]

            current = quiz_state["current_question"]
            context = quiz_state["docs"][current].page_content
            question = quiz_state["questions"][current]

            # Evaluate answer
            eval_chain = self.evaluate_prompt | self.llm
            evaluation = eval_chain.invoke({
                "question": question,
                "answer": answer,
                "context": context
            })

            # Parse evaluation (expecting JSON)
            try:
                eval_result = self._parse_json(evaluation.content)
                score = eval_result["score"]
                feedback = eval_result["feedback"]
            except:
                score = 0
                feedback = "Error parsing evaluation."
                logger.warning(f"Failed to parse evaluation: {evaluation.content}")

            quiz_state["scores"].append(score)

            # Move to next question or end quiz
            quiz_state["current_question"] += 1
            if quiz_state["current_question"] < len(quiz_state["docs"]):
                next_question = self._generate_single_question(quiz_state["docs"][quiz_state["current_question"]].page_content)
                quiz_state["questions"].append(next_question)
                self._save_practice(session_id, quiz_state)
                return {
                    "status": "success",
                    "question_number": quiz_state["current_question"] + 1,
                    "total_questions": len(quiz_state["docs"]),
                    "question": next_question,
                    "previous_feedback": feedback,
                    "previous_score": score
                }
            else:
                avg_score = sum(quiz_state["scores"]) / len(quiz_state["scores"]) if quiz_state["scores"] else 0
                self.store.pop(session_id + "_quiz", None)
                self._save_practice(session_id, {**quiz_state, "complete": True})
                return {
                    "status": "complete",
                    "message": f"Quiz complete! Average score: {avg_score:.1f}/10",
                    "previous_feedback": feedback,
                    "previous_score": score
                }
        except Exception as e:
            logger.error(f"Error submitting quiz answer: {e}")
            raise

if __name__ == "__main__":
    chat = AbhyasamChat()
