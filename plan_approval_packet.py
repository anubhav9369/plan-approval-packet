#!/usr/bin/env python3
"""Build the approval packet for an InspectablePlan.

A human should never approve a plan from memory. This tool gathers
everything an approver needs into one page, before the decision:

  * what the plan is — goal, steps, permission-gated and irreversible ones
  * what it will cost — totals, budget, steps with no estimate (unknown,
    not zero), and blind irreversible steps (irreversible + unpriced)
  * what is risky — ungated irreversible steps, gated steps with no
    failure points, steps with no reason, missing constraints
  * what policy says — spend limit and the every-step-has-a-why rule
  * what happened last time — the latest recorded decision for this plan
    version, and what changed since the previous version

Verdict: READY TO APPROVE, NEEDS WORK, or BLOCKED. BLOCKED means a
human must not approve as-is: an ungated irreversible step, a blind
irreversible step, or a spend over the budget. NEEDS WORK means the
plan is safe to read but incomplete. The packet is a summary — it
never approves anything itself; the decision still goes through
plan-approve.

Usage:
    python3 plan_approval_packet.py examples/plan.json
    python3 plan_approval_packet.py examples/plan.json --previous examples/plan-v1.json
    python3 plan_approval_packet.py examples/plan.json --decisions examples/decisions.jsonl
    python3 plan_approval_packet.py examples/plan.json --budget-usd 1 --json

Exit codes: 0 READY TO APPROVE, 1 NEEDS WORK or BLOCKED, 2 input error.
"""

import argparse
import json
import sys

DEFAULT_BUDGET_MINUTES = 120.0
DEFAULT_BUDGET_USD = 5.0


class PacketError(ValueError):
    """The plan file is not a usable InspectablePlan."""


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _step_text(step):
    return step.get("action") or step.get("text") or ""


def _step_estimate(step):
    est = step.get("estimate")
    if not isinstance(est, dict):
        return None
    minutes = est.get("minutes")
    usd = est.get("usd")
    if not _is_number(minutes) and not _is_number(usd):
        return None
    return {
        "minutes": minutes if _is_number(minutes) else 0.0,
        "usd": usd if _is_number(usd) else 0.0,
    }


def _is_irreversible(step):
    if step.get("irreversible") is True:
        return True
    text = _step_text(step).lower()
    return any(verb in text for verb in ("send ", "delete ", "publish ", "pay "))


def load_plan(path):
    """Load and validate a plan file. Returns the plan dict."""
    try:
        with open(path, encoding="utf-8") as f:
            plan = json.load(f)
    except OSError as exc:
        raise PacketError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PacketError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(plan, dict):
        raise PacketError("plan must be a JSON object")
    steps = plan.get("steps")
    if not isinstance(steps, list):
        raise PacketError("plan must have a 'steps' list")
    seen_ids = set()
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise PacketError(f"step {i} must be an object")
        step_id = step.get("id")
        if not isinstance(step_id, str) or not step_id:
            raise PacketError(f"step {i} must have a non-empty string 'id'")
        if step_id in seen_ids:
            raise PacketError(f"duplicate step id: {step_id}")
        seen_ids.add(step_id)
        if "estimate" in step and _step_estimate(step) is None:
            raise PacketError(f"step {step_id} has an estimate with no numbers")
    return plan


def load_decisions(path):
    """Load a JSONL decisions log. Returns a list of decision dicts."""
    decisions = []
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError as exc:
        raise PacketError(f"cannot read {path}: {exc}") from exc
    for n, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        try:
            decisions.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise PacketError(f"{path} line {n} is not valid JSON: {exc}") from exc
    return decisions


def latest_decision(decisions, plan_id, version):
    """The most recent decision for this exact plan id and version."""
    matches = [d for d in decisions
               if isinstance(d, dict)
               and d.get("plan_id") == plan_id
               and d.get("plan_version") == version]
    return matches[-1] if matches else None


def build_packet(plan, previous=None, decisions=None,
                 budget_minutes=DEFAULT_BUDGET_MINUTES,
                 budget_usd=DEFAULT_BUDGET_USD):
    """Assemble the approval packet. Returns a dict with sections."""
    steps = plan["steps"]
    findings = []  # each: {"severity": "high"|"medium"|"low", "message": str}

    total_minutes = 0.0
    total_usd = 0.0
    unpriced = []
    blind_irreversible = []
    for step in steps:
        est = _step_estimate(step)
        if est is None:
            unpriced.append(step["id"])
        else:
            total_minutes += est["minutes"]
            total_usd += est["usd"]
        if _is_irreversible(step) and est is None:
            blind_irreversible.append(step["id"])
        if _is_irreversible(step) and not step.get("permission_gated"):
            findings.append({"severity": "high",
                             "message": f"step {step['id']} is irreversible "
                                        "but not permission-gated"})
        if step.get("permission_gated") and not step.get("failure_points"):
            findings.append({"severity": "medium",
                             "message": f"step {step['id']} is permission-gated "
                                        "but lists no failure points"})
        if not step.get("why"):
            findings.append({"severity": "medium",
                             "message": f"step {step['id']} has no reason (why)"})

    for step_id in blind_irreversible:
        findings.append({"severity": "high",
                         "message": f"step {step_id} is irreversible and has "
                                    "no cost estimate (blind)"})
    for step_id in unpriced:
        if step_id not in blind_irreversible:
            findings.append({"severity": "medium",
                             "message": f"step {step_id} has no cost estimate"})

    if total_minutes > budget_minutes:
        findings.append({"severity": "high",
                         "message": f"estimated {total_minutes:g} minutes exceeds "
                                    f"the {budget_minutes:g}-minute budget"})
    if total_usd > budget_usd:
        findings.append({"severity": "high",
                         "message": f"estimated ${total_usd:.2f} exceeds "
                                    f"the ${budget_usd:.2f} budget"})
    if not plan.get("constraints"):
        findings.append({"severity": "medium",
                         "message": "plan lists no constraints"})
    if not plan.get("assumptions"):
        findings.append({"severity": "low",
                         "message": "plan lists no assumptions"})

    # What changed since the previous version, if one was given.
    changes = None
    if previous is not None:
        old = {s["id"]: s for s in previous.get("steps", [])}
        new = {s["id"]: s for s in steps}
        added = sorted(set(new) - set(old))
        removed = sorted(set(old) - set(new))
        changed = []
        for step_id in sorted(set(new) & set(old)):
            old_step, new_step = old[step_id], new[step_id]
            diffs = [k for k in ("action", "text", "why", "permission_gated",
                                 "irreversible", "estimate", "failure_points")
                     if old_step.get(k) != new_step.get(k)]
            if diffs:
                changed.append({"id": step_id, "fields": diffs})
        changes = {"added": added, "removed": removed, "changed": changed}

    decision = None
    if decisions is not None:
        decision = latest_decision(decisions, plan.get("id"),
                                   plan.get("version"))

    if any(f["severity"] == "high" for f in findings):
        verdict = "BLOCKED"
    elif findings:
        verdict = "NEEDS WORK"
    else:
        verdict = "READY TO APPROVE"

    return {
        "plan_id": plan.get("id"),
        "version": plan.get("version"),
        "goal": plan.get("goal"),
        "steps": len(steps),
        "gated_steps": sum(1 for s in steps if s.get("permission_gated")),
        "irreversible_steps": sum(1 for s in steps if _is_irreversible(s)),
        "total_minutes": total_minutes,
        "total_usd": round(total_usd, 2),
        "unpriced_steps": unpriced,
        "budget_minutes": budget_minutes,
        "budget_usd": budget_usd,
        "findings": findings,
        "changes": changes,
        "latest_decision": decision,
        "verdict": verdict,
    }


def render_markdown(packet):
    """Render the packet as one readable Markdown page."""
    lines = [
        f"# Approval packet — {packet['plan_id']} (v{packet['version']})",
        "",
        f"**Verdict: {packet['verdict']}**",
        "",
    ]
    if packet.get("goal"):
        lines += [f"Goal: {packet['goal']}", ""]
    lines += [
        "## What the plan is",
        "",
        f"- {packet['steps']} steps, "
        f"{packet['gated_steps']} permission-gated, "
        f"{packet['irreversible_steps']} irreversible",
        "",
        "## What it will cost",
        "",
        f"- Estimated: {packet['total_minutes']:g} minutes, "
        f"${packet['total_usd']:.2f}",
        f"- Budget: {packet['budget_minutes']:g} minutes, "
        f"${packet['budget_usd']:.2f}",
    ]
    if packet["unpriced_steps"]:
        lines.append(f"- Unpriced steps (unknown, not zero): "
                     f"{', '.join(packet['unpriced_steps'])}")
    lines += ["", "## Findings", ""]
    if packet["findings"]:
        for f in packet["findings"]:
            lines.append(f"- [{f['severity'].upper()}] {f['message']}")
    else:
        lines.append("- None.")
    lines += ["", "## What changed since the previous version", ""]
    changes = packet.get("changes")
    if changes is None:
        lines.append("- No previous version given.")
    elif not changes["added"] and not changes["removed"] and not changes["changed"]:
        lines.append("- Nothing changed.")
    else:
        for step_id in changes["added"]:
            lines.append(f"- Added step {step_id}")
        for step_id in changes["removed"]:
            lines.append(f"- Removed step {step_id}")
        for item in changes["changed"]:
            lines.append(f"- Step {item['id']} changed: "
                         f"{', '.join(item['fields'])}")
    lines += ["", "## Latest decision on this version", ""]
    decision = packet.get("latest_decision")
    if decision is None:
        lines.append("- None recorded.")
    else:
        lines.append(f"- {decision.get('decision')} by "
                     f"{decision.get('reviewer', 'unknown')}: "
                     f"{decision.get('reason', '')}")
    lines.append("")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Build the approval packet for an InspectablePlan.")
    parser.add_argument("plan", help="plan JSON file")
    parser.add_argument("--previous", help="previous plan version JSON file")
    parser.add_argument("--decisions", help="JSONL decisions log")
    parser.add_argument("--budget-minutes", type=float,
                        default=DEFAULT_BUDGET_MINUTES)
    parser.add_argument("--budget-usd", type=float, default=DEFAULT_BUDGET_USD)
    parser.add_argument("--json", action="store_true",
                        help="print the packet as JSON instead of Markdown")
    parser.add_argument("--out", help="write the packet to this file")
    args = parser.parse_args(argv)

    try:
        plan = load_plan(args.plan)
        previous = load_plan(args.previous) if args.previous else None
        decisions = (load_decisions(args.decisions)
                     if args.decisions else None)
        packet = build_packet(plan, previous=previous, decisions=decisions,
                              budget_minutes=args.budget_minutes,
                              budget_usd=args.budget_usd)
    except PacketError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    text = (json.dumps(packet, indent=2) if args.json
            else render_markdown(packet))
    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(text if text.endswith("\n") else text + "\n")
        except OSError as exc:
            print(f"error: cannot write {args.out}: {exc}", file=sys.stderr)
            return 2
    else:
        print(text)
    return 0 if packet["verdict"] == "READY TO APPROVE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
