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
            return self.bucket, self.bucket.blob(name)
        for name in ('question_bank._blob', 'cloud_artifacts._blob'):
            mock = patch(name, side_effect=blob); mock.start(); self.addCleanup(mock.stop)

    def test_quiz_delete_and_regenerate_uses_a_new_object(self):
        sets = [quizzes.save_question_set([QUESTION], title=f'Quiz {i}') for i in range(10)]
        with self.assertRaises(quizzes.QuizLimitError): quizzes.save_question_set([QUESTION])
        old = sets[4]
        name = quizzes.PREFIX + old['id'] + '.json'
        quizzes.delete_question_set(old['id'])
        self.assertNotIn(name, self.bucket.items)
        with self.assertRaises(FileNotFoundError): quizzes.get_question_set(old['id'])
        self.assertEqual(len(quizzes.list_question_sets()), 9)
        new = quizzes.save_question_set([QUESTION], title='Replacement quiz')
        self.assertNotEqual(new['id'], old['id'])
        self.assertNotEqual(new['revision'], old['revision'])
        self.assertEqual(len(self.bucket.list_blobs(prefix=quizzes.PREFIX)), 10)

    def test_flashcard_delete_and_regenerate_uses_a_new_object(self):
        cards = [{"front": "Question", "back": "Answer"}]
        saved = [decks.save_deck(cards, f'Page {i}') for i in range(10)]
        with self.assertRaises(quizzes.QuizLimitError): decks.save_deck(cards, 'Too many')
        old = saved[0]
        decks.delete_deck(old['deck_id'])
        name = decks.DECK_PREFIX + old['deck_id'] + '.json'
        self.assertNotIn(name, self.bucket.items)
        with self.assertRaises(FileNotFoundError): decks.get_deck(old['deck_id'])
        self.assertEqual(len(decks.list_decks()), 9)
        new = decks.save_deck(cards, 'New page')
        self.assertNotEqual(new['deck_id'], old['deck_id'])
        self.assertEqual(len(self.bucket.list_blobs(prefix=decks.DECK_PREFIX)), 10)

    def test_legacy_empty_filename_does_not_control_new_ids(self):
        name = quizzes.PREFIX + 'old-human-readable-name.json'
        self.bucket.blob(name).upload_from_string('{}')
        saved = quizzes.save_question_set([QUESTION])
        self.assertNotEqual(saved['id'], 'old-human-readable-name')
        self.assertEqual(len(quizzes.list_question_sets()), 1)

    def test_deleting_twice_is_idempotent(self):
        saved = quizzes.save_question_set([QUESTION])
        quizzes.delete_question_set(saved['id'])
        name = quizzes.PREFIX + saved['id'] + '.json'
        quizzes.delete_question_set(saved['id'])
        self.assertNotIn(name, self.bucket.items)

    def test_missing_object_from_listing_is_ignored(self):
        saved = quizzes.save_question_set([QUESTION])
        name = quizzes.PREFIX + saved['id'] + '.json'
        del self.bucket.items[name]

        self.assertEqual(quizzes.list_question_sets(), [])

    def test_missing_object_during_reuse_does_not_break_save(self):
        saved = quizzes.save_question_set([QUESTION])
        name = quizzes.PREFIX + saved['id'] + '.json'

        original_blob = self.bucket.blob
        def disappearing_blob(blob_name):
            blob = original_blob(blob_name)
            if blob_name == name:
                original_reload = blob.reload
                def reload_then_disappear(**kwargs):
                    del self.bucket.items[blob_name]
                    return original_reload(**kwargs)
                blob.reload = reload_then_disappear
            return blob

        with patch.object(self.bucket, 'blob', side_effect=disappearing_blob):
            replacement = quizzes.save_question_set([QUESTION], title='Replacement')

        self.assertNotEqual(replacement['id'], saved['id'])


if __name__ == '__main__': unittest.main()
