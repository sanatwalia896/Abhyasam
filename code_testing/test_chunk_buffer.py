import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from chunk_buffer import PageBuffer
from mcq_service import MCQService, unique_sources, document_trivia
from json_output import parse_json_response


def source(index, text="Source passage"):
    return {"id": str(index), "text": text, "page_id": "page"}


def doc(page, index, text):
    return SimpleNamespace(page_content=text, metadata={"page_id": page, "chunk_index": index, "page_title": page})


def decision(action, questions=None, **extra):
    return {"decision": action, "reason": "Source supports this decision.", "questions": questions or [], **extra}


def question(ids, text="Why can a callback access a variable after its enclosing function returns?"):
    return {"question": text, "options": {"A": "Lexical closure", "B": "Global promotion", "C": "A new thread", "D": "Dynamic scope"},
            "answer": "A", "explanation": "A closure retains access to its lexical environment.", "source_chunk_ids": ids}


class BufferTests(unittest.TestCase):
    def test_valid_json_with_embedded_code_fences_is_preserved(self):
        data = {"question": "What does this print? ```js\nconsole.log(1);\n```"}
        self.assertEqual(parse_json_response(json.dumps(data)), data)
        self.assertEqual(parse_json_response("```json\n" + json.dumps(data) + "\n```"), data)

    def test_incomplete_outer_json_is_not_replaced_with_inner_fragment(self):
        with self.assertRaises(json.JSONDecodeError):
            parse_json_response('{"questions": [{"question": "unfinished"}')

    def test_maximum_four_original_passages(self):
        buffer = PageBuffer()
        for step in range(6): buffer.update(source(step), step, defer=True)
        self.assertEqual([item["id"] for item in buffer.sources(5)], ["2", "3", "4", "5"])

    def test_character_limit_and_oversized_passage(self):
        buffer = PageBuffer()
        for step in range(3): buffer.update(source(step, "x" * 2500), step, defer=True)
        self.assertEqual(len(buffer.sources(2)), 2)
        buffer.update(source(99, "x" * 6001), 3, defer=True)
        self.assertEqual(len(buffer.sources(3)), 2)

    def test_retaining_old_passage_does_not_reset_age(self):
        buffer = PageBuffer()
        buffer.update(source(0), 0, defer=True)
        buffer.update(None, 4, retain=["0"])
        self.assertEqual(len(buffer.sources(5)), 1)
        self.assertEqual(buffer.sources(6), [])

    def test_consumed_and_explicitly_dropped_passages(self):
        buffer = PageBuffer()
        for step in range(3): buffer.update(source(step), step, defer=True)
        buffer.update(None, 3, consumed=["0", "1"], retain=["1", "invented"], drop=["2"])
        self.assertEqual([item["id"] for item in buffer.sources(3)], ["1"])


class GenerationBufferTests(unittest.TestCase):
    def test_stops_immediately_at_ten_accepted_questions(self):
        texts = [
            "How does lexical scope determine variable visibility?",
            "Which keyword creates a mutable block scoped binding?",
            "When does a promise transition into the fulfilled state?",
            "Why can an event handler access an enclosing parameter?",
            "What happens when a rejected promise lacks a handler?",
            "How should asynchronous operations be combined concurrently?",
            "Which behavior distinguishes object identity from value equality?",
            "When is a default function parameter evaluated?",
            "What effect does returning inside finally have on a result?",
            "Why does destructuring an absent property yield undefined?",
        ]
        def respond(payload):
            self.assertFalse(payload['final_attempt'])
            current = payload['current_chunk']
            self.assertLess(current['chunk_index'], 10)
            return decision('generate', [question([current['id']], texts[current['chunk_index']])])
        docs = [doc('A', i, f'Independent source passage {i} about a useful programming concept.') for i in range(20)]
        service, inputs = self.run_generator(docs, respond)
        with patch('mcq_service.list_question_sets', return_value=[]), patch('mcq_service.save_question_set', return_value={'id': 'saved'}) as save:
            result = service.generate('JavaScript', 10)
        self.assertEqual(result['generated_count'], 10)
        self.assertEqual(len(inputs), 10)
        self.assertEqual(len(save.call_args.args[0]), 10)
        save.assert_called_once()

    def run_generator(self, docs, respond, requested=10):
        inputs = []
        def invoke(prompt):
            payload = json.loads(prompt.split("\nInput JSON:\n")[1])
            inputs.append(payload)
            return SimpleNamespace(content=json.dumps(respond(payload)))
        chat = SimpleNamespace(_retrieve=lambda *args, **kwargs: docs,
                               llm=SimpleNamespace(invoke=invoke), _parse_json=json.loads)
        return MCQService(chat), inputs

    def test_page_order_and_cross_chunk_evidence_without_cross_page_leak(self):
        docs = [doc("B", 0, "Neural networks use layers."), doc("A", 1, "Returned callbacks retain their lexical environment."),
                doc("A", 0, "Closures are a mechanism that will be explained next.")]
        def respond(payload):
            current = payload["current_chunk"]
            if current["page_id"] == "B":
                self.assertEqual(payload["pending_context"], [])
                return decision("skip")
            if current["chunk_index"] == 0: return decision("defer")
            previous = payload["pending_context"][0]
            self.assertEqual(previous["chunk_index"], 0)
            return decision("generate", [question([previous["id"], current["id"]])])
        service, inputs = self.run_generator(docs, respond)
        with patch("mcq_service.list_question_sets", return_value=[]), patch("mcq_service.save_question_set", return_value={"id": "saved"}) as save:
            result = service.generate("closures", 10)
        self.assertEqual(result["generated_count"], 1)
        self.assertEqual(len(result["questions"][0]["source_chunk_ids"]), 2)
        self.assertEqual(len(inputs), 3)
        self.assertNotIn("pending_context", save.call_args.kwargs["generation"])

    def test_one_final_attempt_then_clear(self):
        def respond(payload):
            if payload["final_attempt"]:
                self.assertIsNone(payload["current_chunk"])
                return decision("generate", [question([payload["pending_context"][0]["id"]])])
            return decision("defer")
        service, inputs = self.run_generator([doc("A", 0, "Callbacks retain the enclosing lexical environment.")], respond)
        with patch("mcq_service.list_question_sets", return_value=[]), patch("mcq_service.save_question_set", return_value={"id": "saved"}):
            self.assertEqual(service.generate("closures", 10)["generated_count"], 1)
            self.assertEqual(service.generate("closures", 10)["generated_count"], 1)
        self.assertEqual(len(inputs), 4)
        self.assertEqual(inputs[2]["pending_context"], [])

    def test_all_skipped_does_not_create_empty_quiz(self):
        service, _ = self.run_generator([doc("A", 0, "Guide title and contents")], lambda payload: decision("skip"))
        with patch("mcq_service.list_question_sets", return_value=[]), patch("mcq_service.save_question_set") as save:
            with self.assertRaises(ValueError): service.generate("JavaScript", 10)
        save.assert_not_called()

    def test_trivia_and_fabricated_sources_are_rejected(self):
        def respond(payload):
            source_id = payload["current_chunk"]["id"]
            return decision("generate", [question([source_id], "What is the subtitle of the guide?"), question(["invented"])])
        service, _ = self.run_generator([doc("A", 0, "A passage about closures.")], respond)
        with patch("mcq_service.list_question_sets", return_value=[]), patch("mcq_service.save_question_set") as save:
            with self.assertRaises(ValueError): service.generate("closures", 10)
        save.assert_not_called()

    def test_skip_does_not_accept_questions_or_retain_current(self):
        def respond(payload):
            source_id = payload["current_chunk"]["id"]
            return decision("skip", [question([source_id])], retain_source_ids=[source_id, "invented"])
        service, inputs = self.run_generator([doc("A", 0, "A heading")], respond)
        with patch("mcq_service.list_question_sets", return_value=[]), patch("mcq_service.save_question_set"):
            with self.assertRaises(ValueError): service.generate("closures", 10)
        self.assertEqual(len(inputs), 1)  # No retained passage => no final attempt.

    def test_same_text_on_different_pages_keeps_distinct_sources(self):
        result = unique_sources([doc("A", 0, "Lexical scope"), doc("B", 0, "Lexical scope")])
        self.assertEqual(len(result), 2)
        self.assertNotEqual(result[0]["id"], result[1]["id"])

    def test_filters_document_trivia_but_not_subject_titles(self):
        for text in ("What is the title of this Notion page?", "Which topic is not included in the guide?", "What is the subtitle of the guide?"):
            self.assertTrue(document_trivia(text), text)
        self.assertFalse(document_trivia("Which HTML element sets the browser tab title?"))


if __name__ == "__main__": unittest.main()
