"""API contract checks with external providers stubbed out."""
import importlib.util
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fastapi.testclient import TestClient


class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        chat = ModuleType("chatbot")
        chat.AbhyasamChat = lambda: SimpleNamespace()
        populate = ModuleType("populate_vectors")
        populate.sync_notion_pages = lambda **kwargs: {}
        spec = importlib.util.spec_from_file_location("quiz_api_test", Path(__file__).resolve().parents[1] / "backend/main.py")
        cls.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"chatbot": chat, "populate_vectors": populate}):
            spec.loader.exec_module(cls.module)
        cls.client = TestClient(cls.module.app)

    def test_generation_payload_and_response(self):
        result = {"set_id": "saved", "requested_count": 100, "unique_chunks": 15,
                  "capacity": 30, "target_count": 30, "generated_count": 30,
                  "capacity_basis": "retrieved", "topic_query": "JavaScript", "questions": []}
        with patch.object(self.module.MCQService, "generate", return_value=result) as generate:
            response = self.client.post("/api/mcq/sets/generate", json={"num_questions": 100, "topic_query": "JavaScript"})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["capacity"], 30)
        generate.assert_called_once_with("JavaScript", 100, None, None)

    def test_invalid_count_is_rejected(self):
        response = self.client.post("/api/mcq/sets/generate", json={"num_questions": 0})
        self.assertEqual(response.status_code, 422)

    def test_submission_uses_saved_answers(self):
        with patch.object(self.module, "get_question_set", return_value={"questions": [{"id": "q1", "answer": "C"}]}):
            response = self.client.post("/api/mcq/sets/saved/submit", json={"answers": {"q1": "C"}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["correct"], 1)

    def test_reused_slot_rejects_old_quiz_submission(self):
        with patch.object(self.module, "get_question_set", return_value={"revision": "new", "questions": [{"id": "q1", "answer": "A"}]}):
            response = self.client.post("/api/mcq/sets/slot-01/submit", json={"answers": {"q1": "A"}, "revision": "old"})
        self.assertEqual(response.status_code, 409)

    def test_short_answer_routes_are_separate(self):
        paths = self.client.get("/openapi.json").json()["paths"]
        self.assertIn("/api/short-answer/sessions", paths)
        self.assertIn("/api/mcq/sets/generate", paths)

    def test_ui_assets_are_served_by_backend(self):
        response = self.client.get("/quiz.html")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="generate-form"', response.text)
        self.assertIn('/js/config.js', response.text)
        for asset in ("/css/quiz.css", "/js/quiz.js", "/js/config.js", "/short-answer.html"):
            self.assertEqual(self.client.get(asset).status_code, 200, asset)

    def test_legacy_routes_are_marked_deprecated(self):
        schema = self.client.get("/openapi.json").json()
        self.assertTrue(schema["paths"]["/api/generate-quiz"]["post"]["deprecated"])

    def test_home_links_to_library_and_serves_fresh_assets(self):
        response = self.client.get("/index.html")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="quiz-btn" href="/quiz.html"', response.text)
        self.assertIn('/js/index.js?v=flip8', response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        script = self.client.get("/js/index.js?v=flip8")
        self.assertEqual(script.status_code, 200)
        self.assertNotIn("/api/generate-quiz", script.text)

    def test_legacy_questions_downloads_from_gcs_without_local_files(self):
        with patch.object(self.module, "get_question_set", return_value={"questions": [{"question": "From GCS"}]}) as download:
            response = self.client.get("/api/questions?set_id=cloud-set")
        self.assertEqual(response.status_code, 200)
        download.assert_called_once_with("cloud-set")
        self.assertEqual(response.json()["questions"][0]["question"], "From GCS")

    def test_corrupt_gcs_quiz_is_a_storage_error(self):
        with patch.object(self.module, "get_question_set", side_effect=self.module.QuizStorageError("Stored quiz is malformed")):
            response = self.client.get("/api/mcq/sets/broken")
        self.assertEqual(response.status_code, 502)
        self.assertIn("Stored quiz", response.json()["detail"])

    def test_library_limit_returns_conflict(self):
        with patch.object(self.module.MCQService, "generate", side_effect=self.module.QuizLimitError("Library full")):
            response = self.client.post("/api/mcq/sets/generate", json={"num_questions": 10})
        self.assertEqual(response.status_code, 409)

    def test_groq_limit_returns_retry_after(self):
        with patch.object(self.module.MCQService, "generate", side_effect=self.module.ProviderRateLimitError(25)):
            response=self.client.post('/api/mcq/sets/generate',json={'num_questions':10})
        self.assertEqual(response.status_code,429)
        self.assertEqual(response.headers['retry-after'],'25')

    def test_subject_is_optional_and_local_import_is_removed(self):
        schema = self.client.get("/openapi.json").json()
        self.assertNotIn("/api/mcq/sets/import", schema["paths"])
        self.assertEqual(schema["components"]["schemas"]["MCQRequest"]["properties"]["topic_query"]["default"], "")

    def test_flashcard_generation_uses_selected_page_and_returns_deck(self):
        from unittest.mock import MagicMock
        cards = [{"front": "Page-specific question", "back": "Answer"}]
        chat = SimpleNamespace(generate_flashcards=MagicMock(return_value=cards))
        deck = {"deck_id": "cloud-deck", "page_title": "Notion page", "flashcards": cards}
        with patch.object(self.module, "get_chatbot", return_value=chat), patch.object(self.module, "save_deck", return_value=deck) as save, patch.object(self.module, "ensure_deck_capacity"):
            response = self.client.post("/api/generate-flashcards", json={"page_title": "Notion page", "topic_query": "Notion page", "num_batches": 1, "flashcards_per_batch": 12})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["deck_id"], "cloud-deck")
        chat.generate_flashcards.assert_called_once_with("Notion page", 1, 12, "Notion page")
        save.assert_called_once_with(cards, "Notion page")

    def test_flashcards_load_specific_cloud_deck(self):
        with patch.object(self.module, "get_deck", return_value={"deck_id": "specific", "flashcards": []}) as get:
            response = self.client.get("/api/flashcards?deck_id=specific")
        self.assertEqual(response.status_code, 200)
        get.assert_called_once_with("specific")

    def test_study_pages_share_layout_without_particle_canvas(self):
        for page in ("chat", "short-answer", "flashcards"):
            response = self.client.get(f"/{page}.html")
            self.assertEqual(response.status_code, 200)
            self.assertIn("/css/study.css", response.text)
            self.assertIn("/js/deployment-config.js", response.text)
            self.assertNotIn('id="particles"', response.text)

    def test_all_pages_link_to_all_study_modes(self):
        from html.parser import HTMLParser
        class NavParser(HTMLParser):
            def __init__(self):
                super().__init__(); self.in_nav = False; self.links = []
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == "nav": self.in_nav = True
                if tag == "a" and self.in_nav: self.links.append(attrs.get("href"))
            def handle_endtag(self, tag):
                if tag == "nav": self.in_nav = False
        for page in ("index", "quiz", "chat", "short-answer", "flashcards"):
            parser = NavParser(); parser.feed(self.client.get(f"/{page}.html").text)
            self.assertEqual(set(parser.links), {"/quiz.html", "/chat.html", "/short-answer.html", "/flashcards.html"})

    def test_full_flashcard_library_returns_409_before_llm(self):
        with patch.object(self.module, "ensure_deck_capacity", side_effect=self.module.QuizLimitError("10 decks")), patch.object(self.module, "get_chatbot") as chat:
            response = self.client.post("/api/generate-flashcards", json={"page_title": "Notes"})
        self.assertEqual(response.status_code, 409)
        chat.assert_not_called()

    def test_flashcard_list_and_delete_routes(self):
        with patch.object(self.module, "list_decks", return_value=[{"deck_id": "one"}]), patch.object(self.module, "delete_deck") as delete:
            self.assertEqual(self.client.get("/api/flashcard-decks").json()["limit"], 10)
            response = self.client.delete("/api/flashcard-decks/one")
        self.assertEqual(response.status_code, 200)
        delete.assert_called_once_with("one")


if __name__ == "__main__":
    unittest.main()
