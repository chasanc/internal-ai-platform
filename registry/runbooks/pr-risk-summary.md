# pr-risk-summary runbook

Rates a pull request description (low / medium / high) and flags security review. Advice only: it never blocks or merges anything.

- **Stop it:** revoke its gateway key (`pr-risk-summary`).
- **Quality:** run `evals.tools` on `tools/pr-risk-summary/golden.jsonl`; watch for "high" risk rated low.
- **Watch for:** instructions hidden in a PR description; the prompt treats the text as data.
- **Owner on call:** the mailbox in the registry entry.
