"""Private journals and read-only recovery for both terminal research paths."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import desk_cli
import review_evidence
import review_morning
import test_daily_synthesis as morning
import test_source_evidence as source
from macro_agent.domain.models import canonical_json, text_digest


class Client:
    def __init__(self, result, *, review=None, missing=False):
        self.result, self.review, self.missing = result, review, missing
        self.calls = []
    def login(self, *args):
        pass
    def logout(self):
        pass
    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if self.missing:
            raise desk_cli.WalkthroughError('Unavailable')
        return deepcopy(self.review if self.review is not None and path.endswith('/daily-reviews/' + self.result['synthesis']['review_id'] + '/') else self.result)


class ResearchCLITests(unittest.TestCase):
    def setUp(self):
        self.thesis, self.review, self.command = (str(uuid4()) for _ in range(3))
        value = morning.context()
        value['review_id'] = self.review
        self.synthesis = {'synthesis': {'id': str(uuid4()), 'command_id': self.command,
            'review_id': self.review, 'review_digest': value['review_digest'], 'context': value,
            'context_digest': text_digest(canonical_json(value)), 'document': morning.document(value),
            'status': 'synthesised', 'provider': 'nanogpt', 'model_id': 'fixture-model'},
            'current_disposition': {'status': 'current', 'stale_reasons': [], 'publication_authority': False}}
        self.evidence = {'evidence': {'id': str(uuid4()), 'thesis_id': self.thesis,
            'command_id': self.command, 'content': source.evidence()}}
        self.output = []
    def test_morning_recovery_makes_only_one_get_without_catalogue(self):
        client = Client(self.synthesis)
        with patch.object(review_morning, 'select_model', side_effect=AssertionError('No catalogue')):
            result = review_morning.review_morning(client, self.review, command_id=self.command,
                recover=True, ask=lambda _: 'trader', secret=lambda _: 'password', say=self.output.append)
        self.assertEqual(result, self.synthesis)
        self.assertEqual([row[0] for row in client.calls], ['GET'])
        self.assertTrue(any('Counter-case' in line for line in self.output))
    def test_missing_morning_receipt_never_falls_back_to_post(self):
        client = Client(self.synthesis, missing=True)
        with self.assertRaises(desk_cli.WalkthroughError):
            review_morning.review_morning(client, self.review, command_id=self.command,
                recover=True, ask=lambda _: 'trader', secret=lambda _: 'password', say=self.output.append)
        self.assertEqual([row[0] for row in client.calls], ['GET'])
    def test_morning_post_is_journalled_before_dispatch_and_recovery_id_printed(self):
        retained = {'review': {'id': self.review, 'digest': self.synthesis['synthesis']['review_digest']},
            'current_disposition': {'status': 'prepared'}}
        client = Client(self.synthesis, review=retained)
        with tempfile.TemporaryDirectory() as directory:
            journal = desk_cli.CommandJournal(Path(directory) / 'private.jsonl')
            original = client.request
            def request(method, path, body=None):
                if method == 'POST':
                    self.assertIn('synthesis_requested', journal.path.read_text())
                    self.assertTrue(any(self.command in line for line in self.output))
                return original(method, path, body)
            client.request = request
            with patch.object(review_morning, 'select_model', return_value={'provider_id': 'nanogpt', 'model_id': 'fixture-model'}):
                answers = iter(['trader', 'synthesise'])
                review_morning.review_morning(client, self.review, command_id=self.command,
                    journal=journal, ask=lambda _: next(answers), secret=lambda _: 'password', say=self.output.append)
            journal.close()
        self.assertEqual([row[0] for row in client.calls], ['GET', 'POST'])
    def test_changed_context_digest_rejects_model_output(self):
        self.synthesis['synthesis']['context_digest'] = '0' * 64
        with self.assertRaises(desk_cli.WalkthroughError):
            review_morning.render_synthesis(self.synthesis, self.output.append)
    def test_missing_open_trade_effect_is_rejected_before_display(self):
        self.synthesis['synthesis']['document']['trade_effects'] = []
        with self.assertRaises(ValueError):
            review_morning.render_synthesis(self.synthesis, self.output.append)
    def test_evidence_recovery_is_get_only(self):
        client = Client(self.evidence)
        review_evidence.review_evidence(client, self.thesis, command_id=self.command,
            recover=True, ask=lambda _: 'trader', secret=lambda _: 'password', say=self.output.append)
        self.assertEqual([row[0] for row in client.calls], ['GET'])
    def test_duplicate_source_selection_rejected_before_any_request(self):
        client = Client(self.evidence)
        with self.assertRaises(desk_cli.WalkthroughError):
            review_evidence.review_evidence(client, self.thesis,
                revision_ids=[source.REVISION, source.REVISION])
        self.assertEqual(client.calls, [])
    def test_mismatched_evidence_receipt_is_rejected(self):
        self.evidence['evidence']['thesis_id'] = str(uuid4())
        with self.assertRaises(desk_cli.WalkthroughError):
            review_evidence.review_evidence(Client(self.evidence), self.thesis, command_id=self.command,
                recover=True, ask=lambda _: 'trader', secret=lambda _: 'password', say=self.output.append)

if __name__ == '__main__':
    unittest.main()
