from __future__ import annotations

import argparse
import importlib
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import jumpserver_api.jms_bootstrap as jms_bootstrap

jms_bootstrap.ensure_requirements_installed = lambda *args, **kwargs: None

from jumpserver_api import jms_runtime

jms_diagnose = importlib.import_module("jumpserver_api.jms_diagnose")


ORG_ALPHA = {"id": "11111111-1111-1111-1111-111111111111", "name": "Alpha"}
ORG_BETA = {"id": "22222222-2222-2222-2222-222222222222", "name": "Beta"}
DEFAULT_ORG = {"id": jms_runtime.DEFAULT_ORG_ID, "name": "Default"}
INTERNAL_ORG = {"id": jms_runtime.RESERVED_INTERNAL_ORG_ID, "name": "Internal"}


def _capture_run_and_print(func):
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        exit_code = jms_runtime.run_and_print(func)
    return exit_code, json.loads(stdout.getvalue())


class OrgPromptingTests(unittest.TestCase):
    def test_unresolved_org_error_returns_structured_blocking_payload(self):
        with patch.object(jms_runtime, "current_runtime_values", return_value={}):
            with patch.object(jms_runtime, "list_accessible_orgs", return_value=[ORG_ALPHA, ORG_BETA]):
                exit_code, payload = _capture_run_and_print(jms_runtime.ensure_selected_org_context)

        self.assertEqual(exit_code, 1)
        self.assertEqual(
            payload["error"],
            "Organization selection is required: multiple accessible organizations were detected.",
        )
        details = payload["details"]
        self.assertTrue(details["selection_required"])
        self.assertEqual(details["reason_code"], "organization_selection_required")
        self.assertEqual(
            details["user_message"],
            "检测到多个可访问组织，继续前必须先选择一个组织。",
        )
        self.assertIn(
            "python3 scripts/jumpserver_api/jms_diagnose.py select-org --org-id <org-id> --confirm",
            details["action_hint"],
        )
        self.assertEqual(details["candidate_org_count"], 2)
        self.assertEqual(
            details["org_selection_policy"],
            "required_before_query_when_multiple_accessible_orgs",
        )
        self.assertEqual(details["candidate_orgs"], [ORG_ALPHA, ORG_BETA])
        self.assertIsNone(details["effective_org"])

    def test_active_org_hint_describes_fixed_query_scope(self):
        with patch.object(
            jms_runtime,
            "current_runtime_values",
            return_value={"JMS_ORG_ID": ORG_ALPHA["id"]},
        ):
            with patch.object(jms_runtime, "list_accessible_orgs", return_value=[ORG_ALPHA, ORG_BETA]):
                context = jms_runtime.resolve_effective_org_context(auto_select=False)

        self.assertFalse(context["selection_required"])
        self.assertEqual(context["effective_org"]["id"], ORG_ALPHA["id"])
        self.assertEqual(context["switchable_org_count"], 1)
        self.assertIn("当前查询范围固定为组织 Alpha", context["org_context_hint"])
        self.assertIn(ORG_ALPHA["id"], context["org_context_hint"])
        self.assertIn("如需改查其他组织，请先切换组织。", context["org_context_hint"])

    def test_reserved_auto_select_keeps_behavior_and_uses_new_hint(self):
        with patch.object(jms_runtime, "current_runtime_values", return_value={}):
            with patch.object(jms_runtime, "list_accessible_orgs", return_value=[DEFAULT_ORG, INTERNAL_ORG]):
                with patch.object(jms_runtime, "persist_selected_org") as persist_selected_org:
                    context = jms_runtime.resolve_effective_org_context()

        persist_selected_org.assert_called_once_with(jms_runtime.DEFAULT_ORG_ID)
        self.assertFalse(context["selection_required"])
        self.assertEqual(context["effective_org"]["id"], jms_runtime.DEFAULT_ORG_ID)
        self.assertEqual(context["effective_org"]["source"], "reserved_auto_select")
        self.assertEqual(context["switchable_org_count"], 1)
        self.assertIn("按保留组织规则固定为组织 Default", context["org_context_hint"])
        self.assertIn(jms_runtime.DEFAULT_ORG_ID, context["org_context_hint"])

    def test_select_org_without_org_id_reuses_blocking_payload_when_unresolved(self):
        unresolved_context = {
            "candidate_orgs": [ORG_ALPHA, ORG_BETA],
            "effective_org": None,
            "switchable_orgs": [],
            "switchable_org_count": 0,
            "org_context_hint": None,
            "reserved_org_auto_select_eligible": False,
            "selection_required": True,
        }
        args = argparse.Namespace(org_id=None, confirm=False)
        with patch.object(jms_diagnose, "list_accessible_orgs", return_value=[ORG_ALPHA, ORG_BETA]):
            with patch.object(
                jms_diagnose,
                "resolve_effective_org_context",
                return_value=unresolved_context,
            ):
                result = jms_diagnose._select_org(args)

        expected = jms_runtime.build_org_selection_required_payload(unresolved_context)
        self.assertEqual(result, expected)

    def test_select_org_preview_and_confirm_use_stronger_scope_hints(self):
        unresolved_context = {
            "candidate_orgs": [ORG_ALPHA, ORG_BETA],
            "effective_org": None,
            "switchable_orgs": [],
            "switchable_org_count": 0,
            "org_context_hint": None,
            "reserved_org_auto_select_eligible": False,
            "selection_required": True,
        }

        preview_args = argparse.Namespace(org_id=ORG_ALPHA["id"], confirm=False)
        with patch.object(jms_diagnose, "list_accessible_orgs", return_value=[ORG_ALPHA, ORG_BETA]):
            with patch.object(
                jms_diagnose,
                "resolve_effective_org_context",
                return_value=unresolved_context,
            ):
                preview = jms_diagnose._select_org(preview_args)

        self.assertFalse(preview["selection_required"])
        self.assertEqual(preview["effective_org"]["id"], ORG_ALPHA["id"])
        self.assertIn("当前预览的查询范围将切换为组织 Alpha", preview["org_context_hint"])
        self.assertIn(ORG_ALPHA["id"], preview["org_context_hint"])
        self.assertIn(
            "python3 scripts/jumpserver_api/jms_diagnose.py select-org --org-id %s --confirm"
            % ORG_ALPHA["id"],
            preview["next_step"],
        )

        confirm_args = argparse.Namespace(org_id=ORG_ALPHA["id"], confirm=True)
        persisted = {
            "current_nonsecret": {"JMS_ORG_ID": ORG_ALPHA["id"]},
            "env_file_path": "/tmp/jumpserver.env",
        }
        with patch.object(jms_diagnose, "list_accessible_orgs", return_value=[ORG_ALPHA, ORG_BETA]):
            with patch.object(
                jms_diagnose,
                "resolve_effective_org_context",
                return_value=unresolved_context,
            ):
                with patch.object(jms_diagnose, "persist_selected_org", return_value=persisted):
                    confirmed = jms_diagnose._select_org(confirm_args)

        self.assertFalse(confirmed["selection_required"])
        self.assertEqual(confirmed["current_nonsecret"], persisted["current_nonsecret"])
        self.assertEqual(confirmed["env_file_path"], persisted["env_file_path"])
        self.assertEqual(confirmed["effective_org"]["id"], ORG_ALPHA["id"])
        self.assertIn("当前查询范围固定为组织 Alpha", confirmed["org_context_hint"])
        self.assertIn(ORG_ALPHA["id"], confirmed["org_context_hint"])
        self.assertNotIn("预览", confirmed["org_context_hint"])


if __name__ == "__main__":
    unittest.main()
