import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from google.api_core.exceptions import PreconditionFailed, NotFound
from collection_limit import limited_collection, CollectionBusyError
from question_bank import QuizLimitError


class Bucket:
    def __init__(self):
        self.items = {}; self.sequence = 0

    def list_blobs(self, prefix):
        return [self.blob(name) for name in self.items if name.startswith(prefix)]

    def blob(self, name):
        bucket = self
        class Blob:
            def __init__(self): self.name = name
            generation = None
            def upload_from_string(self, payload, if_generation_match=None, **kwargs):
                if if_generation_match == 0 and name in bucket.items:
                    raise PreconditionFailed('exists')
                if if_generation_match not in (None, 0) and (name not in bucket.items or bucket.items[name][1] != if_generation_match):
                    raise PreconditionFailed('version changed')
                bucket.sequence += 1
                self.generation = bucket.sequence
                bucket.items[name] = (payload, self.generation)
            def reload(self, **kwargs):
                if name not in bucket.items: raise NotFound('missing')
                self.generation = bucket.items[name][1]
            def download_as_text(self, if_generation_match=None, **kwargs):
                if name not in bucket.items: raise NotFound('missing')
                if if_generation_match is not None and if_generation_match != bucket.items[name][1]:
                    raise PreconditionFailed('version changed')
                return bucket.items[name][0]
            def delete(self, if_generation_match=None, **kwargs):
                if name not in bucket.items: raise NotFound('missing')
                if if_generation_match is not None and if_generation_match != bucket.items[name][1]:
                    raise PreconditionFailed('version changed')
                del bucket.items[name]
        return Blob()


class CollectionLimitTests(unittest.TestCase):
    def setUp(self):
        self.bucket = Bucket()
        self.patch = patch('question_bank._blob', side_effect=lambda name: (self.bucket, self.bucket.blob(name)))
        self.patch.start(); self.addCleanup(self.patch.stop)

    def test_tenth_succeeds_eleventh_fails_for_both_collections(self):
        for prefix in ('quiz/question_sets/', 'flashcards/decks/'):
            for number in range(9): self.bucket.items[f'{prefix}{number}.json'] = ('{"occupied":true}', number)
            with limited_collection(prefix):
                self.bucket.blob(f'{prefix}tenth.json').upload_from_string('{"occupied":true}')
            with self.assertRaises(QuizLimitError):
                with limited_collection(prefix): self.fail('An eleventh item was allowed')

    def test_another_instance_cannot_save_under_the_same_lease(self):
        with limited_collection('quiz/question_sets/'):
            with self.assertRaises(CollectionBusyError):
                with limited_collection('quiz/question_sets/'): self.fail('Concurrent save allowed')

    def test_lease_is_removed_after_failed_save(self):
        with self.assertRaises(RuntimeError):
            with limited_collection('flashcards/decks/'): raise RuntimeError('write failed')
        with limited_collection('flashcards/decks/'): pass
        self.assertTrue(all(json.loads(data[0])["expires_at"] == 0 for name, data in self.bucket.items.items() if name.startswith('system/locks/')))

    def test_expired_lease_is_recovered(self):
        with limited_collection('flashcards/decks/'):
            lock = next(name for name in self.bucket.items if name.startswith('system/locks/'))
            self.bucket.items[lock] = (json.dumps({'expires_at': 0}), self.bucket.items[lock][1])
            with limited_collection('flashcards/decks/'): pass


if __name__ == '__main__': unittest.main()
