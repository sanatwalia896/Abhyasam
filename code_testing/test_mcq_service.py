"""Run with python3 -m unittest discover -s code_testing -p test_mcq_service.py."""

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from mcq_service import MCQService, grade, unique_sources, import_questions, is_duplicate
from question_bank import QuizLimitError


def document(text):
    return SimpleNamespace(page_content=text, metadata={"page_title": "Notes"})


class MCQTests(unittest.TestCase):
    def test_requested_100_is_capped_at_30_for_15_chunks(self):
        # Distinct source topics ensure questions are not near-duplicates.
        topics = ["closures", "arrays", "objects", "promises", "events", "modules",
                  "classes", "prototypes", "iterators", "generators", "exceptions",
                  "operators", "symbols", "strings", "numbers"]
        docs = [document(f"{topic} " * 20) for topic in topics]
        sources = unique_sources(docs)

        class LLM:
            calls = 0

            def invoke(self, prompt):
                payload = json.loads(prompt.split("\nInput JSON:\n")[1])
                group = [payload["current_chunk"]] if payload["current_chunk"] else payload["pending_context"]
                questions = []
                for source in group:
                    topic = source["text"].split()[0]
                    questions.extend([
                        {"question": f"Explain {topic} mechanisms?", "options": dict(zip("ABCD", ["One", "Two", "Three", "Four"])),
                         "answer": "B", "source_chunk_ids": [source["id"]], "explanation": "This answer follows from the supplied study material."},
                        {"question": f"When should {topic} be used in production applications?", "options": dict(zip("ABCD", ["One", "Two", "Three", "Four"])),
                         "answer": "A", "source_chunk_ids": [source["id"]], "explanation": "This answer follows from the supplied study material."},
                    ])
                self.calls += 1
                return SimpleNamespace(content=json.dumps({"decision": "generate", "reason": "These passages explain the concepts.", "questions": questions}))

        # For this capacity test keep question text strongly distinct using source hashes.
        llm = LLM()
        chat = SimpleNamespace(_retrieve=lambda *a, **k: docs, llm=llm, _parse_json=json.loads)
        with patch("mcq_service.list_question_sets", return_value=[]), \
             patch("mcq_service.save_question_set", return_value={"id": "saved"}) as save, \
             patch("mcq_service.is_duplicate", side_effect=lambda q, existing: q in existing):
            result = MCQService(chat).generate("JavaScript", 100)
        self.assertEqual(len(sources), 15)
        self.assertEqual(result["capacity"], 30)
        self.assertEqual(result["generated_count"], 30)
        self.assertEqual(llm.calls, 15)
        self.assertEqual(len(save.call_args.args[0]), 30)

    def test_duplicate_and_invalid_questions_do_not_get_saved(self):
        docs = [document("A source discussing JavaScript lexical scope and closures with enough words to qualify as usable study material.")]
        source = unique_sources(docs)[0]["id"]
        question = {"question": "Which keyword declares a block scoped variable?", "options": dict(zip("ABCD", ["let", "var", "static", "define"])), "answer": "A", "source_chunk_ids": [source], "explanation": "Let declares block scoped variables in JavaScript."}
        candidates = [question, question, {**question, "answer": "X"}, {**question, "source_chunk_ids": ["invented"]}]
        chat = SimpleNamespace(_retrieve=lambda *a, **k: docs,
                               llm=SimpleNamespace(invoke=lambda p: SimpleNamespace(content=json.dumps({"decision": "generate", "reason": "Enough evidence.", "questions": candidates}))),
                               _parse_json=json.loads)
        with patch("mcq_service.list_question_sets", return_value=[]), \
             patch("mcq_service.save_question_set", return_value={"id": "saved"}):
            result = MCQService(chat).generate("JavaScript", 100)
        self.assertEqual(result["capacity"], 2)
        self.assertEqual(result["generated_count"], 1)

    def test_duplicate_source_text_does_not_increase_capacity(self):
        text = "Some useful source material about programming variables functions closures and scope that contains at least fifteen words."
        self.assertEqual(len(unique_sources([document(text), document(text.upper())])), 1)

    def test_full_library_stops_before_model_call(self):
        with patch("mcq_service.list_question_sets", return_value=[{}] * 10):
            with self.assertRaisesRegex(QuizLimitError, "10 sets"):
                MCQService(None).generate("topic", 10)

    def test_server_scores_unanswered_and_legacy_ids(self):
        result = grade({"questions": [{"answer": "B"}, {"id": "custom", "answer": "A"}]}, {"q1": "B"})
        self.assertEqual(result["correct"], 1)
        self.assertEqual(result["unanswered"], 1)
        self.assertEqual(result["percentage"], 50)

    def test_import_accepts_reference_repository_format(self):
        raw = {"question": "Which keyword declares a block scoped variable?", "options": ["let", "var", "define", "static"], "answer": 0}
        imported = import_questions([raw, raw])
        self.assertEqual(len(imported), 1)
        self.assertEqual(imported[0]["answer"], "A")

    def test_minor_rewording_is_a_duplicate(self):
        self.assertTrue(is_duplicate("Which keyword declares a block-scoped variable?", ["Which keyword declares a block scoped variable?"]))


if __name__ == "__main__":
    unittest.main()
