import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from test_collection_limit import Bucket
import question_bank as quizzes
import cloud_artifacts as decks


QUESTION = {"id": "q1", "question": "Which keyword creates a block-scoped binding?",
            "options": {"A": "let", "B": "var", "C": "define", "D": "static"}, "answer": "A"}


class StorageSlotTests(unittest.TestCase):
    def setUp(self):
        self.bucket = Bucket()
        def blob(name):
            value = self.bucket.blob(name)
            value.delete = lambda **kwargs: self.fail('A GCS delete was issued')
            return self.bucket, value
        for name in ('question_bank._blob', 'cloud_artifacts._blob'):
            mock = patch(name, side_effect=blob); mock.start(); self.addCleanup(mock.stop)

    def test_quiz_clear_and_regenerate_reuses_the_same_object(self):
        sets = [quizzes.save_question_set([QUESTION], title=f'Quiz {i}') for i in range(10)]
        with self.assertRaises(quizzes.QuizLimitError): quizzes.save_question_set([QUESTION])
        old = sets[4]
        name = quizzes.PREFIX + old['id'] + '.json'
        quizzes.delete_question_set(old['id'])
        self.assertTrue(json.loads(self.bucket.items[name][0])['empty'])
        with self.assertRaises(FileNotFoundError): quizzes.get_question_set(old['id'])
        self.assertEqual(len(quizzes.list_question_sets()), 9)
        new = quizzes.save_question_set([QUESTION], title='Replacement quiz')
        self.assertEqual(new['id'], old['id'])
        self.assertNotEqual(new['revision'], old['revision'])
        self.assertEqual(len(self.bucket.list_blobs(prefix=quizzes.PREFIX)), 10)

    def test_flashcard_clear_and_regenerate_reuses_the_same_object(self):
        cards = [{"front": "Question", "back": "Answer"}]
        saved = [decks.save_deck(cards, f'Page {i}') for i in range(10)]
        with self.assertRaises(quizzes.QuizLimitError): decks.save_deck(cards, 'Too many')
        old = saved[0]
        decks.delete_deck(old['deck_id'])
        name = decks.DECK_PREFIX + old['deck_id'] + '.json'
        self.assertIn(name, self.bucket.items)
        with self.assertRaises(FileNotFoundError): decks.get_deck(old['deck_id'])
        self.assertEqual(len(decks.list_decks()), 9)
        new = decks.save_deck(cards, 'New page')
        self.assertEqual(new['deck_id'], old['deck_id'])
        self.assertEqual(len(self.bucket.list_blobs(prefix=decks.DECK_PREFIX)), 10)

    def test_legacy_empty_filename_is_reused(self):
        name = quizzes.PREFIX + 'old-human-readable-name.json'
        self.bucket.blob(name).upload_from_string('{}')
        saved = quizzes.save_question_set([QUESTION])
        self.assertEqual(saved['id'], 'old-human-readable-name')
        self.assertEqual(len(self.bucket.list_blobs(prefix=quizzes.PREFIX)), 1)

    def test_clearing_twice_does_not_rewrite_content_twice(self):
        saved = quizzes.save_question_set([QUESTION])
        quizzes.delete_question_set(saved['id'])
        name = quizzes.PREFIX + saved['id'] + '.json'
        generation = self.bucket.items[name][1]
        quizzes.delete_question_set(saved['id'])
        self.assertEqual(self.bucket.items[name][1], generation)


if __name__ == '__main__': unittest.main()
