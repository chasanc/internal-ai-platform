# supplier-delay-triage runbook

Classifies a supplier delay notice by cause and severity and drafts an acknowledgement. A planner edits and sends; it never agrees to new terms.

- **Stop it:** revoke its gateway key (`supplier-delay-triage`).
- **Quality:** run `evals.tools` on `tools/supplier-delay-triage/golden.jsonl`; watch for long delays rated low.
- **Watch for:** drafts that accept new terms or dates; the reviewer is the control.
- **Owner on call:** the mailbox in the registry entry.
