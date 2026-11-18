#!/usr/bin/env python3
"""Tests for plan_approval_packet.py (standard library only)."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plan_approval_packet import (PacketError, build_packet, latest_decision,
                                  load_decisions, load_plan, render_markdown)

CLEAN = {
    "id": "p1", "version": 2, "goal": "Summarise papers",
    "assumptions": ["PDFs available"], "constraints": ["Do not share"],
    "steps": [
        {"id": "s1", "action": "Fetch the papers",
         "estimate": {"minutes": 5, "usd": 0.1}, "why": "Source first"},
        {"id": "s2", "action": "Send the summary to the reviewer",
         "estimate": {"minutes": 5, "usd": 0.4}, "why": "Reviewer waits",
         "permission_gated": True, "failure_points": ["Wrong address"]},
    ],
}


def _plan(**overrides):
    plan = json.loads(json.dumps(CLEAN))
    plan.update(overrides)
    return plan


class TestPacket(unittest.TestCase):
    def test_clean_plan_is_ready(self):
        packet = build_packet(_plan())
        self.assertEqual(packet["verdict"], "READY TO APPROVE")
        self.assertEqual(packet["findings"], [])
        self.assertEqual(packet["total_minutes"], 10.0)
        self.assertEqual(packet["total_usd"], 0.5)
        self.assertEqual(packet["gated_steps"], 1)
        self.assertEqual(packet["irreversible_steps"], 1)

    def test_ungated_irreversible_is_blocked(self):
        plan = _plan()
        plan["steps"][1].pop("permission_gated")
        packet = build_packet(plan)
        self.assertEqual(packet["verdict"], "BLOCKED")
        self.assertTrue(any("not permission-gated" in f["message"]
                            for f in packet["findings"]
                            if f["severity"] == "high"))

    def test_unpriced_irreversible_is_blind(self):
        plan = _plan()
        plan["steps"][1].pop("estimate")
        packet = build_packet(plan)
        self.assertEqual(packet["verdict"], "BLOCKED")
        self.assertTrue(any("blind" in f["message"] for f in packet["findings"]))
        self.assertIn("s2", packet["unpriced_steps"])

    def test_over_budget_is_blocked(self):
        plan = _plan()
        plan["steps"][0]["estimate"] = {"minutes": 5, "usd": 9.0}
        packet = build_packet(plan)
        self.assertEqual(packet["verdict"], "BLOCKED")
        self.assertTrue(any("exceeds" in f["message"] for f in packet["findings"]))

    def test_missing_why_is_needs_work(self):
        plan = _plan()
        plan["steps"][0].pop("why")
        packet = build_packet(plan)
        self.assertEqual(packet["verdict"], "NEEDS WORK")
        self.assertTrue(any("no reason" in f["message"] for f in packet["findings"]))

    def test_gated_step_without_failure_points(self):
        plan = _plan()
        plan["steps"][1].pop("failure_points")
        packet = build_packet(plan)
        self.assertEqual(packet["verdict"], "NEEDS WORK")
        self.assertTrue(any("no failure points" in f["message"]
                            for f in packet["findings"]))

    def test_diff_against_previous_version(self):
        previous = _plan(version=1)
        previous["steps"][1].pop("permission_gated")
        previous["steps"][1].pop("failure_points")
        packet = build_packet(_plan(), previous=previous)
        self.assertEqual(len(packet["changes"]["changed"]), 1)
        self.assertEqual(packet["changes"]["changed"][0]["id"], "s2")
        self.assertIn("permission_gated",
                      packet["changes"]["changed"][0]["fields"])

    def test_latest_decision_picks_this_version(self):
        decisions = [
            {"plan_id": "p1", "plan_version": 1, "decision": "request-changes",
             "reviewer": "akhila", "reason": "Ungated send"},
            {"plan_id": "p1", "plan_version": 2, "decision": "approve",
             "reviewer": "akhila", "reason": "Fixed"},
            {"plan_id": "other", "plan_version": 2, "decision": "reject",
             "reviewer": "x", "reason": "No"},
        ]
        decision = latest_decision(decisions, "p1", 2)
        self.assertEqual(decision["decision"], "approve")
        packet = build_packet(_plan(), decisions=decisions)
        self.assertEqual(packet["latest_decision"]["decision"], "approve")

    def test_markdown_shows_verdict_and_findings(self):
        plan = _plan()
        plan["steps"][0].pop("why")
        packet = build_packet(plan)
        text = render_markdown(packet)
        self.assertIn("Verdict: NEEDS WORK", text)
        self.assertIn("[MEDIUM]", text)
        self.assertIn("10 minutes, $0.50", text)

    def test_load_plan_rejects_bad_input(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json",
                                         delete=False) as f:
            f.write('{"steps": [{"id": "s1"}, {"id": "s1"}]}')
            path = f.name
        try:
            with self.assertRaises(PacketError):
                load_plan(path)
        finally:
            os.unlink(path)
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl",
                                         delete=False) as f:
            f.write('{"plan_id": "p1"}\nnot json\n')
            path = f.name
        try:
            with self.assertRaises(PacketError):
                load_decisions(path)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
