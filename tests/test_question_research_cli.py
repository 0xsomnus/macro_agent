"""Question research keeps exact input and recovers through read-only calls."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))

import desk_cli
import research_question as cli


EXACT = "  Could fictional helium supply disruption create an exposure idea?\r\nΔ"
MODEL = {"provider_id": "nanogpt", "model_id": "recorded-model"}


def receipt():
    return {"research": {"id": str(uuid4()), "command_id": str(uuid4()), "thesis_id": str(uuid4()),
        "exact_question": EXACT, "status": "planning", "provider": "nanogpt", "model_id": "recorded-model",
        "costs": {"total_known_cost_usd": None}, "plan": None, "discoveries": [], "compilation": None,
        "gaps": ["This recorded receipt contains no research finding."], "authority": {
            "monitoring_started": False, "thesis_approved": False, "positions_created": False}}, "replayed": False}


class Client:
    def __init__(self, result=None, *, missing=False, mutate=None):
        self.result = result or receipt()
        self.calls, self.logins, self.logouts = [], [], 0
        self.missing, self.mutate = missing, mutate
        self.before_request = None

    def login(self, username, password):
        self.logins.append((username, password))

    def logout(self):
        self.logouts += 1

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if self.before_request:
            self.before_request(method, path, body)
        if self.missing:
            raise desk_cli.WalkthroughError("Response unavailable")
        value = deepcopy(self.result)
        if method == "POST" and path == "/api/v1/research/":
            value["research"].update(command_id=body["command_id"], exact_question=body["exact_question"])
        if self.mutate:
            self.mutate(value)
        return value


def answers(*items):
    values = iter(items)
    return lambda _: next(values)


class QuestionResearchCLITests(unittest.TestCase):
    def setUp(self):
        self.output = []

    def run_cli(self, client, **kwargs):
        return cli.research(client, secret=lambda _: "private-password", say=self.output.append, **kwargs)

    def test_exact_question_and_selected_model_are_journalled_before_one_post(self):
        client = Client()
        with tempfile.TemporaryDirectory() as directory:
            journal = desk_cli.CommandJournal(Path(directory) / "private.jsonl")
            def before(method, path, body):
                records = [json.loads(line) for line in journal.path.read_text().splitlines()]
                self.assertEqual(records[0]["kind"], "research_requested")
                self.assertEqual(records[0]["detail"]["request"], body)
                self.assertEqual(body["exact_question"], EXACT)
                self.assertTrue(any(body["command_id"] in line for line in self.output))
            client.before_request = before
            try:
                with patch.object(cli, "select_model", return_value=MODEL):
                    result = self.run_cli(client, exact_question=EXACT, journal=journal,
                        ask=answers("trader", "research"))
                records = [json.loads(line) for line in journal.path.read_text().splitlines()]
                self.assertEqual([row["kind"] for row in records], ["research_requested", "research_response"])
                self.assertEqual(result["research"]["exact_question"], EXACT)
            finally:
                journal.close()
        self.assertEqual([(row[0], row[1]) for row in client.calls], [("POST", "/api/v1/research/")])
        self.assertEqual(client.logouts, 1)
        self.assertTrue(any("No monitoring is enrolled" in line for line in self.output))

    def test_command_recovery_is_get_only_without_catalogue_or_private_journal(self):
        client = Client()
        command_id = client.result["research"]["command_id"]
        with patch.object(cli, "select_model", side_effect=AssertionError("No catalogue during recovery")):
            result = self.run_cli(client, recover_command=command_id, ask=answers("trader"))
        self.assertEqual(result, client.result)
        self.assertEqual(client.calls, [("GET", f"/api/v1/research-commands/{command_id}/", None)])
        self.assertEqual(client.logouts, 1)

    def test_failed_or_uncertain_plan_is_visible_on_read_only_recovery(self):
        for status, reason in (("failed", "invalid_model_output"),
                               ("outcome_unknown", "timeout")):
            client = Client()
            client.result["research"]["plan"] = {
                "status": status, "stop_reason": reason, "document": None}
            command_id = client.result["research"]["command_id"]
            output = []
            with self.subTest(status=status), patch.object(cli, "select_model",
                    side_effect=AssertionError("Recovery cannot call a catalogue")):
                cli.research(client, recover_command=command_id, ask=answers("trader"),
                    secret=lambda _: "private-password", say=output.append)
            self.assertIn("Planning state: " + json.dumps(status), output)
            self.assertIn("Planning outcome: " + json.dumps(reason), output)
            self.assertEqual(client.calls, [
                ("GET", f"/api/v1/research-commands/{command_id}/", None)])
            self.assertFalse(any("Named questions" in line for line in output))

    def test_show_run_is_get_only_and_missing_recovery_never_falls_back_to_post(self):
        client = Client()
        run_id = client.result["research"]["id"]
        with patch.object(cli, "select_model", side_effect=AssertionError("No catalogue during reads")):
            self.run_cli(client, show_run=run_id, ask=answers("trader"))
        self.assertEqual(client.calls, [("GET", f"/api/v1/research/{run_id}/", None)])
        missing = Client(missing=True)
        with self.assertRaises(desk_cli.WalkthroughError):
            self.run_cli(missing, recover_command=str(uuid4()), ask=answers("trader"))
        self.assertEqual([row[0] for row in missing.calls], ["GET"])
        self.assertEqual(missing.logouts, 1)

    def test_explicit_continuation_inspects_first_and_journals_before_post(self):
        client = Client()
        run_id = client.result["research"]["id"]
        with tempfile.TemporaryDirectory() as directory:
            journal = desk_cli.CommandJournal(Path(directory) / "continue.jsonl")
            def before(method, path, body):
                if method == "POST":
                    records = [json.loads(line) for line in journal.path.read_text().splitlines()]
                    self.assertEqual(records[0]["kind"], "research_continuation_requested")
                    self.assertEqual(records[0]["detail"], {"run_id": run_id, "request": {}})
            client.before_request = before
            try:
                with patch.object(cli, "select_model", side_effect=AssertionError("Pinned model cannot be replaced")):
                    self.run_cli(client, continue_run=run_id, journal=journal, ask=answers("trader", "continue"))
            finally:
                journal.close()
        self.assertEqual([(row[0], row[1]) for row in client.calls], [
            ("GET", f"/api/v1/research/{run_id}/"), ("POST", f"/api/v1/research/{run_id}/continue/")])
        self.assertTrue(any("will not be resent" in line for line in self.output))

    def test_unconfirmed_continuation_remains_read_only(self):
        client = Client()
        run_id = client.result["research"]["id"]
        self.run_cli(client, continue_run=run_id, ask=answers("trader", ""))
        self.assertEqual([row[0] for row in client.calls], ["GET"])

    def test_canceling_research_or_model_selection_creates_no_research_request(self):
        for selection, prompts in ((MODEL, ("trader", "")), (None, ("trader",))):
            client = Client()
            with patch.object(cli, "select_model", return_value=selection):
                self.assertIsNone(self.run_cli(client, exact_question=EXACT, ask=answers(*prompts)))
            self.assertEqual(client.calls, [])
            self.assertEqual(client.logouts, 1)

    def test_missing_private_journal_blocks_a_consequential_request(self):
        client = Client()
        with patch.object(cli, "select_model", return_value=MODEL), self.assertRaisesRegex(
                desk_cli.WalkthroughError, "private journal"):
            self.run_cli(client, exact_question=EXACT, ask=answers("trader", "research"))
        self.assertEqual(client.calls, [])

    def test_unknown_post_outcome_retains_command_and_never_retries(self):
        client = Client(missing=True)
        with tempfile.TemporaryDirectory() as directory:
            journal = desk_cli.CommandJournal(Path(directory) / "unknown.jsonl")
            try:
                with patch.object(cli, "select_model", return_value=MODEL), self.assertRaisesRegex(
                        desk_cli.WalkthroughError, "--recover-command") as raised:
                    self.run_cli(client, exact_question=EXACT, journal=journal, ask=answers("trader", "research"))
                saved = json.loads(journal.path.read_text().splitlines()[0])["detail"]["request"]
                self.assertIn(saved["command_id"], str(raised.exception))
                self.assertEqual(saved["exact_question"], EXACT)
                self.assertIn("cost may be unknown", str(raised.exception))
            finally:
                journal.close()
        self.assertEqual([row[0] for row in client.calls], ["POST"])
        self.assertEqual(client.logouts, 1)

    def test_mismatched_response_cannot_change_question_or_model(self):
        for field, replacement in (("exact_question", "changed"), ("provider", "openrouter"),
                                   ("model_id", "another-model"), ("command_id", str(uuid4()))):
            client = Client(mutate=lambda value, key=field, changed=replacement: value["research"].update({key: changed}))
            with tempfile.TemporaryDirectory() as directory:
                journal = desk_cli.CommandJournal(Path(directory) / "mismatch.jsonl")
                try:
                    with patch.object(cli, "select_model", return_value=MODEL), self.assertRaisesRegex(
                            desk_cli.WalkthroughError, "changed its request"):
                        self.run_cli(client, exact_question=EXACT, journal=journal, ask=answers("trader", "research"))
                finally:
                    journal.close()
            self.assertEqual([row[0] for row in client.calls], ["POST"])

    def test_research_output_cannot_claim_approval_monitoring_or_positions(self):
        for authority in ("monitoring_started", "thesis_approved", "positions_created"):
            value = receipt()
            value["research"]["authority"][authority] = True
            with self.subTest(authority=authority), self.assertRaisesRegex(desk_cli.WalkthroughError, "authority"):
                cli.render_research(value, self.output.append)

    def test_saved_operation_does_not_accept_a_new_question_or_model(self):
        for kwargs in ({"recover_command": str(uuid4()), "exact_question": EXACT},
                       {"continue_run": str(uuid4()), "requested_model": "replacement"},
                       {"show_run": str(uuid4()), "continue_run": str(uuid4())}):
            client = Client()
            with self.assertRaises(desk_cli.WalkthroughError):
                self.run_cli(client, **kwargs)
            self.assertEqual(client.logins, [])
            self.assertEqual(client.calls, [])

    def test_question_file_preserves_crlf_unicode_and_whitespace(self):
        with tempfile.TemporaryDirectory() as directory:
            question_file = Path(directory) / "question.txt"
            question_file.write_bytes(EXACT.encode())
            journal_file = Path(directory) / "private.jsonl"
            with patch.object(cli, "research") as research, patch.object(cli, "DeskClient"):
                self.assertEqual(cli.main(["--question-file", str(question_file), "--journal", str(journal_file)]), 0)
            self.assertEqual(research.call_args.kwargs["exact_question"], EXACT)
            self.assertEqual(journal_file.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
