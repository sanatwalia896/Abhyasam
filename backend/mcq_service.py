"""MCQ generation and scoring, independent of chat and short-answer sessions."""

import hashlib
import json
import random
import re
import os
import logging
from collections import Counter
from difflib import SequenceMatcher
from itertools import groupby
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from question_bank import list_question_sets, save_question_set, QuizLimitError
from chunk_buffer import PageBuffer

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


def unique_sources(documents, filter_junk=True, min_chunk_length=50):
    """Extract unique source chunks from documents, optionally filtering junk."""
    result = []
    seen = set()
    for order, document in enumerate(documents):
        text = document.page_content.strip()

        # Pre-filter junk chunks to save API calls
        if filter_junk and is_junk_chunk(text, min_length=min_chunk_length):
            continue

        key = normalize(text)
        page_id = str(document.metadata.get("page_id") or document.metadata.get("page_title") or f"unknown-source-{order}")
        source_key = (page_id, key)
        if not key or source_key in seen:
            continue
        seen.add(source_key)
        try:
            chunk_index = int(document.metadata.get("chunk_index", order))
        except (ValueError, TypeError):
            chunk_index = order

        # Extract block metadata
        block_id = document.metadata.get("block_id", "")
        block_type = document.metadata.get("block_type", "")
        block_index = document.metadata.get("block_index", -1)

        result.append({
            "id": hashlib.sha256((page_id + ":" + key).encode()).hexdigest()[:16],
            "text": text,
            "page_id": page_id,
            "chunk_index": chunk_index,
            "page_title": document.metadata.get("page_title", ""),
            "block_id": block_id,
            "block_type": block_type,
            "block_index": block_index,
        })
    return sorted(result, key=lambda source: (source["page_id"], source["chunk_index"]))


class GeneratedMCQ(MCQ):
    explanation: str = Field(min_length=15)
    source_chunk_ids: list[str] = Field(min_length=1, max_length=5)


class ChunkDecision(BaseModel):
    decision: Literal["generate", "defer", "skip"]
    reason: str = Field(min_length=1, max_length=1000)
    questions: list[dict] = Field(default_factory=list, max_length=10)
    retain_source_ids: list[str] = Field(default_factory=list, max_length=5)
    drop_source_ids: list[str] = Field(default_factory=list, max_length=5)


def document_trivia(question):
    """Reject obvious document trivia; subject terms such as HTML title remain valid."""
    question = normalize(question)
    return bool(re.search(
        r"(?:title|subtitle|heading|author|filename|file name|table of contents|chapter count|number of chapters).*\b(?:guide|document|notion page|notes|article|tutorial)\b"
        r"|\b(?:guide|document|notion page|article|tutorial)\b.*(?:titled|subtitle|written by|authored by|does not (?:include|cover)|not (?:included|covered))"
        r"|\b(?:which|what) (?:topic|topics|subject|subjects).*\b(?:not covered|not included|excluded)\b"
        r"|\b(?:not covered|not included|excluded)\b.*\b(?:guide|document|notion page|article|tutorial)\b"
        r"|\b(?:guide|document|notion page|article|tutorial)\b.*\b(?:cover|covers|include|includes|contain|contains)\b",
        question,
    ))


def is_junk_chunk(text: str, min_length: int = 50) -> bool:
    """Filter out chunks that are unlikely to produce good MCQs."""
    text = text.strip()

    # Too short
    if len(text) < min_length:
        return True

    # Only whitespace/punctuation
    if not re.search(r'\w{3,}', text):
        return True

    # Just a heading (single line, ends with common heading patterns)
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    if len(lines) == 1:
        # Single line with title-like patterns
        if re.match(r'^(?:\d+\.?\s+)?[A-Z][^.!?]*$', text):
            return True
        # Single line that's very short
        if len(text) < 80:
            return True

    # Navigation/UI text patterns
    navigation_patterns = [
        r'^(?:home|back|next|previous|menu|contents|index|search)$',
        r'^(?:click|tap|press|select)\s+(?:here|below|above)',
        r'^(?:see|refer to|go to)\s+(?:page|section|chapter)',
        r'^\[(?:image|video|audio|file|link|attachment)\]',
        r'^(?:source|reference|citation):\s*$',
    ]
    text_lower = text.lower()
    if any(re.search(pattern, text_lower) for pattern in navigation_patterns):
        return True

    # Excessive special characters (likely formatting/code)
    alphanumeric = sum(c.isalnum() for c in text)
    if alphanumeric > 0 and len(text) / alphanumeric > 3:
        return True

    # Page metadata patterns
    metadata_patterns = [
        r'^page \d+ of \d+',
        r'^(?:created|modified|updated|last edited)(?:\s+(?:on|at|by))?:',
        r'^(?:author|by|written by|tags|category):',
    ]
    if any(re.search(pattern, text_lower) for pattern in metadata_patterns):
        return True

    return False


def sample_sources_by_blocks(sources, sample_size=25, group_size=3):
    """
    Randomly sample sources with block grouping for better context.

    Groups adjacent blocks together (by block_index), then randomly samples groups.
    This preserves related content while reducing total chunks to process.

    Args:
        sources: List of source dictionaries with block_index
        sample_size: Target number of chunks to return
        group_size: How many adjacent blocks to group together

    Returns:
        Randomly sampled list of sources with related blocks grouped
    """
    if not sources:
        return []

    # Separate sources with and without block info
    with_blocks = [s for s in sources if s.get("block_index", -1) >= 0]
    without_blocks = [s for s in sources if s.get("block_index", -1) < 0]

    sampled = []

    # Sample from sources with block info (group by adjacent blocks)
    if with_blocks:
        # Sort by page and block index
        sorted_blocks = sorted(with_blocks, key=lambda s: (s["page_id"], s["block_index"]))

        # Create groups of adjacent blocks
        groups = []
        current_group = []
        current_page = None
        last_block_idx = -1

        for source in sorted_blocks:
            page_id = source["page_id"]
            block_idx = source["block_index"]

            # Start new group if different page or non-adjacent block
            if (current_page != page_id or
                (last_block_idx >= 0 and block_idx > last_block_idx + 1) or
                len(current_group) >= group_size):

                if current_group:
                    groups.append(current_group)
                current_group = [source]
                current_page = page_id
            else:
                current_group.append(source)

            last_block_idx = block_idx

        if current_group:
            groups.append(current_group)

        # Randomly sample groups
        num_groups = max(1, sample_size // group_size)
        if len(groups) <= num_groups:
            # Use all groups if we don't have enough
            sampled = [chunk for group in groups for chunk in group]
        else:
            selected_groups = random.sample(groups, num_groups)
            sampled = [chunk for group in selected_groups for chunk in group]

    # If we still need more samples, add from sources without block info
    remaining = sample_size - len(sampled)
    if remaining > 0 and without_blocks:
        num_to_sample = min(remaining, len(without_blocks))
        sampled.extend(random.sample(without_blocks, num_to_sample))

    # If still not enough, sample more from with_blocks
    remaining = sample_size - len(sampled)
    if remaining > 0 and with_blocks:
        additional_needed = min(remaining, len(with_blocks) - len(sampled))
        if additional_needed > 0:
            available = [s for s in with_blocks if s not in sampled]
            if available:
                sampled.extend(random.sample(available, min(additional_needed, len(available))))

    # Shuffle to mix different groups
    random.shuffle(sampled)

    return sampled[:sample_size]


class MCQService:
    def __init__(self, chat):
        self.chat = chat

    def sources(self, topic, page_title, max_retrieve=None):
        """Retrieve and filter source chunks for MCQ generation."""
        filters = {"source": "Notion"}
        if page_title:
            filters["page_title"] = page_title

        # Get max chunks from env or use default
        if max_retrieve is None:
            max_retrieve = int(os.getenv("MCQ_MAX_CHUNKS", "80"))

        # Retrieve chunks from vector DB
        documents = self.chat._retrieve(topic, filters, k=max_retrieve)

        # Get minimum chunk length from env
        min_length = int(os.getenv("MCQ_MIN_CHUNK_LENGTH", "50"))

        # Filter and extract unique sources, removing junk
        return unique_sources(documents, filter_junk=True, min_chunk_length=min_length)

    def generate(self, topic, requested, page_title=None, title=None):
        if len(list_question_sets()) >= 10:
            raise QuizLimitError("Your library contains 10 sets. Clear one before generating another.")

        topic = topic.strip() or page_title or "the supplied study material"

        # Retrieve and filter sources
        all_sources = self.sources(topic, page_title)
        if not all_sources:
            raise ValueError("No usable source chunks found. Sync this page before generating a quiz.")

        # Get sample size from env or calculate
        sample_size = int(os.getenv("MCQ_SAMPLE_SIZE", "25"))

        # Random sample with block grouping to reduce API calls
        sources = sample_sources_by_blocks(
            all_sources,
            sample_size=min(sample_size, len(all_sources)),
            group_size=3
        )

        capacity = 2 * len(sources)
        target = min(requested, capacity)
        if not target:
            raise ValueError("No usable source chunks found after sampling.")

        questions = []
        counts = Counter()
        buffers: dict[str, PageBuffer] = {}
        decisions = Counter()

        def process(current, pending, final_attempt=False):
            available = pending + ([current] if current else [])
            budget = min(target - len(questions), 2, sum(max(0, 2 - counts[source["id"]]) for source in available))
            if not available or budget <= 0:
                return None, set()
            payload = {
                "topic": topic, "maximum_questions": budget,
                "final_attempt": final_attempt, "current_chunk": current,
                "pending_context": pending,
                "already_accepted_questions": [item["question"] for item in questions[-20:]],
            }
            prompt = (
                "You are creating practice MCQs for students. Read the study passages and decide: GENERATE, DEFER, or SKIP.\n\n"
                "SKIP if passage is: page title/heading alone, navigation text, metadata, table of contents, "
                "incomplete fragment, or lists without explanations.\n\n"
                "GENERATE only if passage contains complete testable concepts, explains principles/processes, "
                "or provides factual knowledge with context. Prefer reasoning and application questions. "
                "Never force multiple questions from one chunk. Avoid repeating accepted questions.\n\n"
                "DEFER if passage is promising but needs more context (pending passages will be provided).\n\n"
                "Each question must have: question (string), options (object with A/B/C/D keys), "
                "answer (A/B/C/D), explanation (string), source_chunk_ids (array of IDs used).\n\n"
                "When final_attempt is true: generate if justified, otherwise skip (no more context coming).\n\n"
                "Return ONLY valid JSON with these exact keys:\n"
                "- decision: \"generate\" or \"defer\" or \"skip\"\n"
                "- reason: string (1-1000 chars)\n"
                "- questions: array of question objects (max 10, can be empty)\n"
                "- retain_source_ids: array of strings (max 5, can be empty)\n"
                "- drop_source_ids: array of strings (max 5, can be empty)\n\n"
                "Input:\n" + json.dumps(payload, ensure_ascii=False)
            )
            try:
                raw_json = self._generate_json(prompt)
                logger.debug("MCQ chunk decision JSON: %s", json.dumps(raw_json)[:500])

                # Validate with more helpful error messages
                try:
                    result = ChunkDecision.model_validate(raw_json)
                except Exception as validation_error:
                    logger.error("ChunkDecision validation failed: %s", str(validation_error))
                    logger.error("Problematic JSON keys: %s", list(raw_json.keys()) if isinstance(raw_json, dict) else type(raw_json))
                    logger.error("Full JSON: %s", json.dumps(raw_json, indent=2)[:2000])

                    # Try to provide helpful error message
                    if not isinstance(raw_json, dict):
                        raise QuizGenerationError(
                            f"Model returned {type(raw_json).__name__} instead of JSON object. "
                            "Check GROQ_MODEL supports JSON mode."
                        ) from validation_error

                    missing_keys = set(['decision', 'reason', 'questions', 'retain_source_ids', 'drop_source_ids']) - set(raw_json.keys())
                    if missing_keys:
                        raise QuizGenerationError(
                            f"Model JSON missing required keys: {missing_keys}. "
                            f"Got keys: {list(raw_json.keys())}"
                        ) from validation_error

                    raise QuizGenerationError(
                        f"Model JSON validation failed: {str(validation_error)[:300]}"
                    ) from validation_error

            except QuizGenerationError:
                raise
            except (ValueError, TypeError) as error:
                logger.error("Invalid chunk decision: %s", str(error))
                raise QuizGenerationError(
                    f"Failed to generate chunk decision: {str(error)[:200]}"
                ) from error
            decisions[result.decision] += 1
            allowed = {source["id"] for source in available}
            result.retain_source_ids = [key for key in result.retain_source_ids if key in allowed]
            result.drop_source_ids = [key for key in result.drop_source_ids if key in allowed]
            consumed = set()
            if result.decision == "generate":
                accepted_this_step = 0
                for candidate in result.questions:
                    if accepted_this_step >= budget:
                        break
                    try:
                        item = GeneratedMCQ.model_validate(candidate)
                    except (ValueError, TypeError):
                        continue
                    support = set(item.source_chunk_ids)
                    if not support or not support <= allowed:
                        continue
                    anchors = [key for key in sorted(support) if counts[key] < 2]
                    if not anchors or document_trivia(item.question):
                        continue
                    if is_duplicate(item.question, [question["question"] for question in questions]):
                        continue
                    item.source_chunk_id = min(anchors, key=lambda key: counts[key])
                    item.source_chunk_ids = sorted(support)
                    item.id = f"q{len(questions) + 1}"
                    questions.append(item.model_dump())
                    counts[item.source_chunk_id] += 1
                    consumed.update(support)
                    accepted_this_step += 1
            elif current and result.decision == "skip":
                result.retain_source_ids = [key for key in result.retain_source_ids if key != current["id"]]
            logger.info("MCQ progress: decision=%s accepted=%d/%d pending_passages=%d",
                        result.decision, len(questions), target, len(pending))
            return result, consumed

        for page_id, page_sources in groupby(sources, key=lambda source: source["page_id"]):
            buffer = buffers.setdefault(page_id, PageBuffer())
            last_step = -1
            try:
                for step, source in enumerate(page_sources):
                    last_step = step
                    if len(questions) >= target:
                        break
                    result, consumed = process(source, buffer.sources(step))
                    if result:
                        buffer.update(source, step, retain=result.retain_source_ids,
                                      drop=result.drop_source_ids, consumed=consumed,
                                      defer=result.decision == "defer")
                if len(questions) < target:
                    # One final attempt per page. Unresolved material is discarded.
                    process(None, buffer.sources(last_step), final_attempt=True)
            finally:
                buffer.clear()
            if len(questions) >= target:
                break

        if not questions:
            raise ValueError("The model produced no valid unique MCQs. No set was saved; please retry.")
        details = {
            "topic_query": topic,
            "requested_count": requested,
            "total_chunks_retrieved": len(all_sources),
            "sampled_chunks": len(sources),
            "unique_chunks": len(sources),
            "capacity": capacity,
            "target_count": target,
            "generated_count": len(questions),
            "capacity_basis": "random sample with block grouping to reduce API calls",
            "chunk_decisions": dict(decisions),
        }
        saved = save_question_set(
            questions,
            title=title or f"{page_title or topic} — {len(questions)} MCQs",
            page_title=page_title,
            generation=details,
        )
        return {"set_id": saved["id"], "questions": questions, **details}

    def _generate_json(self, prompt):
        """Request JSON mode and regenerate once if output is malformed/truncated."""
        llm = self.chat.llm
        if hasattr(llm, "bind"):
            llm = llm.bind(
                response_format={"type": "json_object"},
                max_tokens=int(os.getenv("MCQ_MAX_OUTPUT_TOKENS", "2048")),
                temperature=0.3
            )
        for attempt in range(2):
            response = llm.invoke(prompt)
            try:
                if getattr(response, "response_metadata", {}).get("finish_reason") == "length":
                    logger.warning("MCQ response truncated, retrying with simplified prompt")
                    raise ValueError("Model output was truncated")

                content = response.content
                logger.debug("MCQ raw response (first 500 chars): %s", content[:500])

                parsed = self.chat._parse_json(content)

                # Ensure all required keys exist with defaults
                if not isinstance(parsed, dict):
                    raise ValueError("Response is not a JSON object")

                parsed.setdefault("decision", "skip")
                parsed.setdefault("reason", "No reason provided")
                parsed.setdefault("questions", [])
                parsed.setdefault("retain_source_ids", [])
                parsed.setdefault("drop_source_ids", [])

                return parsed

            except (json.JSONDecodeError, ValueError, TypeError) as error:
                logger.warning("MCQ JSON parse error (attempt %d): %s", attempt + 1, str(error))
                if attempt:
                    raise QuizGenerationError(
                        "The model returned malformed or incomplete quiz JSON after two attempts. "
                        "No new quiz was saved. Try a smaller question count."
                    ) from error
                prompt += "\n\nYour previous response was invalid. Return ONLY a valid JSON object with keys: decision, reason, questions, retain_source_ids, drop_source_ids."


def grade(question_set, answers):
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


def import_questions(items):
    """Accept canonical MCQs or the reference repo's options-array format."""
    questions = []
    for raw in items:
        item = dict(raw)
        if isinstance(item.get("options"), list) and len(item["options"]) == 4:
            item["options"] = dict(zip("ABCD", item["options"]))
            if type(item.get("answer")) is int and 0 <= item["answer"] <= 3:
                item["answer"] = "ABCD"[item["answer"]]
        question = MCQ.model_validate(item)
        if is_duplicate(question.question, [q["question"] for q in questions]):
            continue
        question.id = f"q{len(questions)+1}"
        questions.append(question.model_dump())
    if not questions:
        raise ValueError("No valid questions in this file")
    return questions
