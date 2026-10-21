"""Background consent stays explicit and saved reads cannot advance research."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))

import desk_cli
import research_background as cli
from test_question_research_cli import answers, receipt


class Client:
    def __init__(self):
        self.research = receipt()
        self.research["research"]["request_digest"] = "a" * 64
        self.run_id = self.research["research"]["id"]
        self.result = {"job": {"id": str(uuid4()), "run_id": self.run_id,
            "owner_id": str(uuid4()),
            "status": "pending", "provider": "nanogpt", "model_id": "recorded-model",
            "next_due_at": None, "last_stop_reason": "waiting_source", "policy": {},
            "model_configuration": {}}}
        self.calls, self.logins, self.logouts = [], [], 0
        self.before_post, self.fail_post = None, False

    def login(self, username, password):
        self.logins.append((username, password))

    def logout(self):
        self.logouts += 1

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "POST":
            if self.before_post:
                self.before_post(body)
            if self.fail_post:
                raise desk_cli.WalkthroughError("Unknown response")
        return deepcopy(self.result if "/background/" in path else self.research)


class ResearchBackgroundCLITests(unittest.TestCase):
    def call(self, client, operation, **kwargs):
        return cli.background(client, client.run_id, operation, secret=lambda _: "private-password",
            say=lambda _: None, **kwargs)

    def test_status_is_one_get_without_journal_or_model_selection(self):
        client = Client()
        self.assertEqual(self.call(client, "status", ask=answers("trader")), client.result)
        self.assertEqual(client.calls, [("GET", f"/api/v1/research/{client.run_id}/background/", None)])
        self.assertEqual(client.logouts, 1)

    def test_consent_binds_reviewed_digest_and_is_journalled_before_post(self):
        client = Client()
        with tempfile.TemporaryDirectory() as directory:
            journal = desk_cli.CommandJournal(Path(directory) / "enroll.jsonl")
            def before(body):
                saved = json.loads(journal.path.read_text().splitlines()[0])
                self.assertEqual(saved["detail"]["request"], body)
                self.assertEqual(body["expected_request_digest"], "a" * 64)
                self.assertEqual(saved["detail"]["run_id"], client.run_id)
            client.before_post = before
            try:
                self.call(client, "enroll", journal=journal, ask=answers("trader", "background"))
                self.assertNotIn("private-password", journal.path.read_text())
            finally:
                journal.close()
        self.assertEqual([item[0] for item in client.calls], ["GET", "POST"])

    def test_cancelled_consent_never_posts(self):
        client = Client()
        with tempfile.TemporaryDirectory() as directory:
            journal = desk_cli.CommandJournal(Path(directory) / "cancel.jsonl")
            try:
                self.assertIsNone(self.call(client, "enroll", journal=journal, ask=answers("trader", "")))
                self.assertEqual(journal.path.read_text(), "")
            finally:
                journal.close()
        self.assertEqual([item[0] for item in client.calls], ["GET"])

    def test_unknown_response_preserves_command_and_never_repeats_post(self):
        client = Client()
        client.fail_post = True
        with tempfile.TemporaryDirectory() as directory:
            journal = desk_cli.CommandJournal(Path(directory) / "unknown.jsonl")
            try:
                with self.assertRaisesRegex(desk_cli.WalkthroughError, "--status"):
                    self.call(client, "enroll", journal=journal, ask=answers("trader", "background"))
                saved = json.loads(journal.path.read_text().splitlines()[0])
                self.assertIn("command_id", saved["detail"]["request"])
            finally:
                journal.close()
        self.assertEqual([item[0] for item in client.calls], ["GET", "POST"])

    def test_changes_require_private_journal_before_login(self):
        for operation in ("enroll", "revoke"):
            client = Client()
            with self.subTest(operation=operation), self.assertRaisesRegex(desk_cli.WalkthroughError, "private journal"):
                self.call(client, operation)
            self.assertEqual((client.logins, client.calls), ([], []))

    def test_foreign_research_response_cannot_be_enrolled(self):
        client = Client()
        client.research["research"]["id"] = str(uuid4())
        with tempfile.TemporaryDirectory() as directory:
            journal = desk_cli.CommandJournal(Path(directory) / "foreign.jsonl")
            try:
                with self.assertRaisesRegex(desk_cli.WalkthroughError, "another request"):
                    self.call(client, "enroll", journal=journal, ask=answers("trader", "background"))
            finally:
                journal.close()
        self.assertEqual([item[0] for item in client.calls], ["GET"])

    def test_revoke_is_saved_once_without_advancing_research(self):
        client = Client()
        client.result["job"]["status"] = "revoked"
        with tempfile.TemporaryDirectory() as directory:
            journal = desk_cli.CommandJournal(Path(directory) / "revoke.jsonl")
            try:
                self.call(client, "revoke", journal=journal, ask=answers("trader"))
            finally:
                journal.close()
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0][:2], ("POST", f"/api/v1/research/{client.run_id}/background/revoke/"))


if __name__ == "__main__":
    unittest.main()
