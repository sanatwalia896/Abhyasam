"""Checks for downloaded GCS JSON and malformed LLM output."""
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from mcq_service import MCQService, QuizGenerationError
from question_bank import get_question_set, QuizStorageError


class StorageTests(unittest.TestCase):
    def test_downloads_gcs_object(self):
        blob = MagicMock()
        blob.download_as_text.return_value = json.dumps({"id": "cloud", "questions": [{
            "question": "A cloud question?", "options": dict(zip("ABCD", ["a", "b", "c", "d"])), "answer": "C",
        }]})
        with patch("question_bank._blob", return_value=(None, blob)):
            saved = get_question_set("cloud")
        blob.download_as_text.assert_called_once_with(timeout=30)
        self.assertEqual(saved["questions"][0]["id"], "q1")

    def test_bad_gcs_json_has_storage_error(self):
        blob = MagicMock()
        blob.name = "quiz/question_sets/broken.json"
        blob.download_as_text.return_value = '{"questions":['
        with patch("question_bank._blob", return_value=(None, blob)):
            with self.assertRaisesRegex(QuizStorageError, "Stored object"):
                get_question_set("broken")

    def test_malformed_generation_is_retried_once(self):
        llm = SimpleNamespace(invoke=MagicMock(side_effect=[
            SimpleNamespace(content='{"questions":['),
            SimpleNamespace(content='{"questions":[]}'),
        ]))
        chat = SimpleNamespace(llm=llm, _parse_json=json.loads)
        self.assertEqual(MCQService(chat)._generate_json("prompt"), {"questions": []})
        self.assertEqual(llm.invoke.call_count, 2)

    def test_repeated_bad_output_has_generation_error(self):
        llm = SimpleNamespace(invoke=MagicMock(return_value=SimpleNamespace(content="broken")))
        with self.assertRaisesRegex(QuizGenerationError, "No new quiz was saved"):
            MCQService(SimpleNamespace(llm=llm, _parse_json=json.loads))._generate_json("prompt")
        self.assertEqual(llm.invoke.call_count, 2)


if __name__ == "__main__":
    unittest.main()
