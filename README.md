# plan-approval-packet

Build the one page a human reads before deciding on an InspectablePlan.

Approving from memory is how bad plans get a yes. The packet gathers
everything an approver needs — what the plan is, what it will cost,
what is risky, what policy says, what happened last time, and what
changed since the previous version — and ends with a verdict:
**READY TO APPROVE**, **NEEDS WORK**, or **BLOCKED**.

The packet never approves anything itself. The decision still goes
through `plan-approve`; this is what the human reads first.

Part of [BRJP26100123](https://github.com/anubhav9369/trustworthy-agentic-ai)
— Building Trustworthy AI Systems through Explainability and
Human-in-the-Loop Control. Week 2: human-in-the-loop.

## Usage

```bash
python3 plan_approval_packet.py examples/plan.json
python3 plan_approval_packet.py examples/plan.json --previous examples/plan-v1.json
python3 plan_approval_packet.py examples/plan.json --decisions examples/decisions.jsonl
python3 plan_approval_packet.py examples/plan.json --budget-usd 1 --json
```

Exit codes: `0` READY TO APPROVE, `1` NEEDS WORK or BLOCKED,
`2` input error.

## What goes in the packet

- **What the plan is** — step count, permission-gated and irreversible steps
- **What it will cost** — totals against the budget; a step with no
  estimate is unknown, not zero, and an irreversible step with no
  estimate is flagged as blind
- **Findings** — ungated irreversible steps and blind irreversible steps
  are HIGH; unpriced steps, gated steps with no failure points, steps
  with no reason, and missing constraints are MEDIUM
- **What changed** — steps added, removed, or changed since `--previous`
- **Latest decision** — the most recent decision for this exact plan
  version from a `--decisions` JSONL log

## Examples

- `examples/plan.json` — clean v2: the send step is now gated with
  failure points. Packet verdict: **READY TO APPROVE**.
- `examples/plan-v1.json` — v1, sent back for changes.
- `examples/decisions.jsonl` — v1 was sent back: "Sending the summary
  is irreversible but not permission-gated".
- `examples/risky-plan.json` — ungated publish step, no reason, $6.50
  over the $5 budget. Packet verdict: **BLOCKED**.
- `examples/packet.md`, `examples/risky-packet.md` — the generated packets.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

10 tests, standard library only.
