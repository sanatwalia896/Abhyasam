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
from langchain_huggingface import HuggingFaceEndpointEmbeddings
from langchain_core.output_parsers import JsonOutputParser

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

class AbhyasamChat:
    """Abhyasam AI: Chat and quiz generation from Notion knowledge base with page-specific filtering."""

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

        # Base retriever for document retrieval
        self.retriever = self.vectorstore.as_retriever(
            search_type="mmr",
            search_kwargs={"k": 6, "lambda_mult": 0.25, "namespace": "notion-knowledge"}
        )

        # Prompt for question answering
        self.base_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are Abhyasam AI. Answer student questions clearly based on the provided Notion context:\n{context}"),
            MessagesPlaceholder(variable_name="history"),
            ("human", "{question}")
        ])

        # Prompt for MCQ quiz generation (escaped curly braces in JSON example)
        self.quiz_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are Abhyasam AI, a teacher AI. Create only MCQ quizzes from the provided Notion context. "
                      "Each question must have 4 options (A, B, C, D) and specify the correct answer as a letter (A, B, C, or D). "
                      "Return the output as JSON: [{{question: str, options: {{A: str, B: str, C: str, D: str}}, answer: str}}]"),
            ("human", "Generate exactly {num_questions} MCQ questions from the following study material:\n\n{context}")
        ])

        # Prompt for generating a single open-ended question
        self.generate_question_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a teacher AI. Generate one clear, open-ended question to test understanding from the provided Notion context. Just output the question."),
            ("human", "{context}")
        ])

        # Prompt for evaluating user's answer (escaped curly braces in JSON)
        self.evaluate_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a teacher AI. Evaluate the student's answer based on the question and Notion context. "
                      "Return JSON: {{'score': int, 'feedback': str}}"),
            ("human", "Question: {question}\nStudent Answer: {answer}\nContext: {context}")
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

        # Quiz chain for MCQ generation (no history)
        self.quiz_chain = (
            {"context": lambda x: x["context"], "num_questions": lambda x: x["num_questions"]}
            | self.quiz_prompt
            | self.llm
            | JsonOutputParser()
        )

    def get_session_history(self, session_id: str) -> ChatMessageHistory:
        """Retrieve or create session history for chat."""
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
            filter_dict = {"source": "Notion"}
            if page_title:
                filter_dict["page_title"] = page_title
                logger.info(f"Generating quiz for page_title: {page_title}")

            docs = self.retriever.invoke(topic_query, filter=filter_dict)
            context = "\n\n".join([doc.page_content for doc in docs])

            if not context:
                logger.warning("No context retrieved for quiz generation.")
                return []

            for batch in range(num_batches):
                logger.info(f"Generating quiz batch {batch + 1}/{num_batches}")
                result = self.quiz_chain.invoke({
                    "context": context,
                    "num_questions": questions_per_batch
                })
                all_questions.extend(result)

            all_questions = all_questions[:30]

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

            with open("data/questions.json", "w") as f:
                json.dump(formatted_questions, f, indent=2)
            logger.info(f"Dumped {len(formatted_questions)} questions to data/questions.json")

            return formatted_questions
        except Exception as e:
            logger.error(f"Error in quiz generation: {e}")
            return []

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
            original_k = self.retriever.search_kwargs['k']
            self.retriever.search_kwargs['k'] = max(20, num_questions * 2)
            docs = self.retriever.invoke("generate diverse quiz questions", filter=filter_dict)
            self.retriever.search_kwargs['k'] = original_k

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

            return {
                "status": "success",
                "question": question,
                "question_number": 1,
                "total_questions": num_questions
            }
        except Exception as e:
            logger.error(f"Error starting quiz: {e}")
            return {"status": "error", "message": "Failed to start quiz."}

    def _generate_single_question(self, context: str) -> str:
        """Generate a single open-ended question from context."""
        question_chain = self.generate_question_prompt | self.llm
        return question_chain.invoke({"context": context}).content.strip()

    def submit_quiz_answer(self, session_id: str, answer: str) -> Dict[str, any]:
        """Evaluate user's answer and return feedback or next question."""
        try:
            quiz_state = self.store.get(session_id + "_quiz")
            if not quiz_state:
                return {"status": "error", "message": "No active quiz session."}

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
                eval_result = json.loads(evaluation.content)
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
                del self.store[session_id + "_quiz"]  # Clear quiz state
                return {
                    "status": "complete",
                    "message": f"Quiz complete! Average score: {avg_score:.1f}/10",
                    "previous_feedback": feedback,
                    "previous_score": score
                }
        except Exception as e:
            logger.error(f"Error submitting quiz answer: {e}")
            return {"status": "error", "message": "Failed to process answer."}

if __name__ == "__main__":
    chat = AbhyasamChat()