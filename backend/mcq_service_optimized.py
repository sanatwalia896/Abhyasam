"""
OPTIMIZED MCQ Service - Batch Processing Version

Key improvements:
1. Batches 3-5 chunks per API call (instead of 1 per call)
2. Removed DEFER mechanism (just GENERATE or SKIP)
3. Reduced output tokens from 2048 to 500
4. Better pre-filtering before API calls
5. Smaller default sample size (15 instead of 25)

Expected savings:
- API calls: 25 → 5-8 (70% reduction)
- Tokens: ~77,700 → ~15,000 (80% reduction)
- Time: 5+ min → 30-60 seconds
"""

import hashlib
import json
import random
import re
import os
import logging
from collections import Counter
from difflib import SequenceMatcher
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from question_bank import list_question_sets, save_question_set, QuizLimitError

logger = logging.getLogger(__name__)


class QuizGenerationError(RuntimeError):
    """The model did not return a usable question set."""


class MCQ(BaseModel):
    id: str = ""
    question: str = Field(min_length=8)
    options: dict[str, str]
    answer: str
    explanation: str = ""
    source_chunk_id: str = ""
    source_chunk_ids: list[str] = Field(default_factory=list)

    @field_validator("options")
    @classmethod
    def check_options(cls, options):
        if set(options) != set("ABCD"):
            raise ValueError("Options must have exactly A, B, C, D")
        if any(not value.strip() for value in options.values()):
            raise ValueError("Options cannot be blank")
        if len({normalize(value) for value in options.values()}) != 4:
            raise ValueError("Options must be distinct")
        return options

    @field_validator("answer")
    @classmethod
    def check_answer(cls, answer):
        answer = answer.strip().upper()
        if answer not in "ABCD" or len(answer) != 1:
            raise ValueError("Answer must be A, B, C, or D")
        return answer


def normalize(text):
    return " ".join(re.findall(r"\w+", text.casefold()))


def is_duplicate(question, existing):
    key = normalize(question)
    words = set(key.split())
    for previous in existing:
        other = normalize(previous)
        other_words = set(other.split())
        if key == other or SequenceMatcher(None, key, other).ratio() >= .88:
            return True
        union = words | other_words
        if union and len(words & other_words) / len(union) >= .85:
            return True
    return False


def is_junk_chunk(text: str, min_length: int = 50) -> bool:
    """Filter out chunks that are unlikely to produce good MCQs."""
    text = text.strip()
    if len(text) < min_length:
        return True
    if not re.search(r'\w{3,}', text):
        return True

    lines = [line.strip() for line in text.split('\n') if line.strip()]
    if len(lines) == 1:
        if re.match(r'^(?:\d+\.?\s+)?[A-Z][^.!?]*$', text):
            return True
        if len(text) < 80:
            return True

    text_lower = text.lower()
    navigation_patterns = [
        r'^(?:home|back|next|previous|menu|contents|index|search)$',
        r'^(?:click|tap|press|select)\s+(?:here|below|above)',
        r'^\[(?:image|video|audio|file|link|attachment)\]',
    ]
    if any(re.search(pattern, text_lower) for pattern in navigation_patterns):
        return True

    alphanumeric = sum(c.isalnum() for c in text)
    if alphanumeric > 0 and len(text) / alphanumeric > 3:
        return True

    return False


def unique_sources(documents, filter_junk=True, min_chunk_length=50):
    """Extract unique source chunks from documents, filtering junk."""
    result = []
    seen = set()
    for order, document in enumerate(documents):
        text = document.page_content.strip()

        if filter_junk and is_junk_chunk(text, min_length=min_chunk_length):
            continue

        key = normalize(text)
        page_id = str(document.metadata.get("page_id") or f"unknown-{order}")
        source_key = (page_id, key)
        if not key or source_key in seen:
            continue
        seen.add(source_key)

        try:
            chunk_index = int(document.metadata.get("chunk_index", order))
        except (ValueError, TypeError):
            chunk_index = order

        result.append({
            "id": hashlib.sha256((page_id + ":" + key).encode()).hexdigest()[:16],
            "text": text[:300],  # TRUNCATE to save tokens!
            "page_id": page_id,
            "chunk_index": chunk_index,
            "page_title": document.metadata.get("page_title", ""),
        })
    return sorted(result, key=lambda s: (s["page_id"], s["chunk_index"]))


def sample_sources_random(sources, sample_size=15):
    """Randomly sample sources (simpler than block grouping)."""
    if len(sources) <= sample_size:
        return sources
    return random.sample(sources, sample_size)


class BatchDecision(BaseModel):
    """Decision for a batch of chunks."""
    questions: list[dict] = Field(default_factory=list, max_length=10)


class MCQServiceOptimized:
    def __init__(self, chat):
        self.chat = chat

    def sources(self, topic, page_title, max_retrieve=None):
        """Retrieve and filter source chunks."""
        filters = {"source": "Notion"}
        if page_title:
            filters["page_title"] = page_title

        if max_retrieve is None:
            max_retrieve = int(os.getenv("MCQ_MAX_CHUNKS", "50"))  # Reduced from 80

        documents = self.chat._retrieve(topic, filters, k=max_retrieve)
        min_length = int(os.getenv("MCQ_MIN_CHUNK_LENGTH", "60"))  # Stricter

        return unique_sources(documents, filter_junk=True, min_chunk_length=min_length)

    def generate(self, topic, requested, page_title=None, title=None):
        if len(list_question_sets()) >= 10:
            raise QuizLimitError("Your library contains 10 sets. Clear one before generating another.")

        topic = topic.strip() or page_title or "the supplied study material"

        # Retrieve and filter sources
        all_sources = self.sources(topic, page_title)
        if not all_sources:
            raise ValueError("No usable source chunks found. Sync this page before generating a quiz.")

        # Get sample size from env
        sample_size = int(os.getenv("MCQ_SAMPLE_SIZE", "15"))  # Reduced from 25!

        # Random sample
        sources = sample_sources_random(all_sources, min(sample_size, len(all_sources)))

        logger.info(f"MCQ: Sampled {len(sources)} from {len(all_sources)} chunks")

        # BATCH PROCESSING: Process chunks in groups
        batch_size = int(os.getenv("MCQ_BATCH_SIZE", "4"))  # Process 4 chunks at once
        questions = []
        existing_questions = set()
        total_question_count = 0  # Track total across all batches

        for batch_start in range(0, len(sources), batch_size):
            if len(questions) >= requested:
                break

            batch = sources[batch_start:batch_start + batch_size]
            remaining = requested - len(questions)

            logger.info(f"MCQ: Processing batch {batch_start//batch_size + 1}, need {remaining} more questions")

            try:
                batch_questions = self._process_batch(batch, topic, remaining, existing_questions, total_question_count)

                for q in batch_questions:
                    if len(questions) >= requested:
                        break
                    if not is_duplicate(q["question"], existing_questions):
                        # Ensure unique ID across all batches
                        total_question_count += 1
                        q["id"] = f"q{total_question_count}"
                        questions.append(q)
                        existing_questions.add(q["question"])
                        logger.info(f"MCQ: Accepted question #{len(questions)}")

            except Exception as e:
                logger.warning(f"MCQ: Batch failed: {e}, continuing...")
                continue

        if not questions:
            raise ValueError("The model produced no valid MCQs. Please retry.")

        # Validate all questions have unique IDs
        question_ids = [q.get("id") for q in questions]
        if len(set(question_ids)) != len(question_ids):
            logger.error(f"Duplicate IDs found: {question_ids}")
            raise ValueError("Generated questions have duplicate IDs")

        logger.info(f"MCQ: Successfully generated {len(questions)} questions with IDs: {question_ids}")

        # Save question set
        saved = save_question_set(
            questions,
            title=title or f"{page_title or topic} — {len(questions)} MCQs",
            page_title=page_title,
            generation={
                "topic_query": topic,
                "requested_count": requested,
                "generated_count": len(questions),
                "total_chunks": len(all_sources),
                "sampled_chunks": len(sources),
                "method": "batch_processing_optimized"
            },
        )

        # Return response matching API expectations
        return {
            "set_id": saved["id"],
            "questions": questions,
            "requested_count": requested,
            "unique_chunks": len(sources),
            "capacity": len(sources) * 2,  # Approximate capacity
            "target_count": min(requested, len(sources) * 2),
            "generated_count": len(questions),
            "capacity_basis": "batch processing with random sampling",
            "topic_query": topic,
            "chunk_decisions": {"batch_processed": len(sources)},
        }

    def _process_batch(self, batch, topic, max_questions, existing_questions, start_question_id=0):
        """Process a batch of chunks in one API call."""

        # Build simplified prompt
        chunks_text = "\n\n".join([
            f"CHUNK {i+1} (id: {chunk['id']}):\n{chunk['text']}"
            for i, chunk in enumerate(batch)
        ])

        prompt = f"""Generate {max_questions} multiple-choice questions from these study passages about {topic}.

RULES:
- SKIP chunks that are: titles, headings, navigation, metadata, incomplete fragments
- ONLY generate from chunks with complete testable concepts
- Each question needs: question, options (A/B/C/D), answer, explanation, source_chunk_ids
- Avoid questions similar to these: {list(existing_questions)[:3]}

PASSAGES:
{chunks_text}

Return JSON: {{"questions": [...]}}
Each question: {{"question": str, "options": {{"A": str, "B": str, "C": str, "D": str}}, "answer": str (A/B/C/D), "explanation": str, "source_chunk_ids": [str]}}
"""

        try:
            raw_json = self._generate_json(prompt)
            result = BatchDecision.model_validate(raw_json)

            # Validate and clean questions
            valid_questions = []
            chunk_ids = {c["id"] for c in batch}

            for q_data in result.questions:
                try:
                    q = MCQ.model_validate(q_data)

                    # Ensure source_chunk_ids are from this batch
                    if q.source_chunk_ids and any(sid in chunk_ids for sid in q.source_chunk_ids):
                        # Don't set ID here - will be set in main loop to ensure uniqueness
                        q.source_chunk_id = q.source_chunk_ids[0] if q.source_chunk_ids else ""
                        valid_questions.append(q.model_dump())

                except Exception as e:
                    logger.debug(f"Skipping invalid question: {e}")
                    continue

            return valid_questions[:max_questions]

        except Exception as e:
            logger.error(f"Batch processing failed: {e}")
            return []

    def _generate_json(self, prompt):
        """Request JSON mode with REDUCED output tokens."""
        llm = self.chat.llm
        if hasattr(llm, "bind"):
            llm = llm.bind(
                response_format={"type": "json_object"},
                max_tokens=500,  # REDUCED from 2048!
                temperature=0.3
            )

        response = llm.invoke(prompt)
        content = response.content

        parsed = json.loads(content) if isinstance(content, str) else content

        # Ensure required keys
        if not isinstance(parsed, dict):
            raise ValueError("Response is not a JSON object")

        parsed.setdefault("questions", [])

        return parsed


def grade(question_set, answers):
    """Grade quiz answers."""
    review = []
    for index, question in enumerate(question_set["questions"]):
        question_id = question.get("id") or f"q{index + 1}"
        selected = answers.get(question_id)
        review.append({
            **question, "id": question_id, "selected": selected,
            "correct": selected == question["answer"],
        })
    correct = sum(item["correct"] for item in review)
    return {
        "correct": correct, "total": len(review),
        "unanswered": sum(item["selected"] is None for item in review),
        "percentage": round(correct * 100 / len(review), 1) if review else 0,
        "review": review,
    }
