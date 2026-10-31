import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from contextlib import nullcontext

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from question_bank import QuizLimitError
import cloud_artifacts as artifacts
from test_collection_limit import Bucket


class CloudArtifactsTests(unittest.TestCase):
    def test_decks_are_isolated_and_reloaded_from_storage(self):
        bucket = Bucket()
        def blob(name): return bucket, bucket.blob(name)
        with patch.object(artifacts, '_blob', side_effect=blob), patch('question_bank._blob', side_effect=blob):
            first = artifacts.save_deck([{'front': 'Question one', 'back': 'Answer one'}], 'Page one')
            second = artifacts.save_deck([{'front': 'Question two', 'back': 'Answer two'}], 'Page two')
            self.assertNotEqual(first['deck_id'], second['deck_id'])
            loaded = artifacts.get_deck(first['deck_id'])
            self.assertEqual(loaded['page_title'], 'Page one')
            self.assertEqual(loaded['flashcards'][0]['back'], 'Answer one')

    def test_session_key_does_not_use_raw_user_input(self):
        name = artifacts.session_name('chat', '../session')
        self.assertTrue(name.startswith('sessions/chat/'))
        self.assertNotIn('..', name)
        self.assertNotEqual(name, artifacts.session_name('short-answer', '../session'))

    def test_ten_decks_stops_before_creating_more(self):
        with patch.object(artifacts, 'list_decks', return_value=[{}] * 10):
            with self.assertRaises(QuizLimitError):
                artifacts.ensure_deck_capacity()


if __name__ == '__main__':
    unittest.main()
