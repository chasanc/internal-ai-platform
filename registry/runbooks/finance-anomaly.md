# finance-anomaly runbook

Flags unusual invoice lines for an analyst. It reads data and writes nothing back; a flag is a prompt to look, not a decision.

- **Stop it:** revoke its gateway key (`finance-anomaly`); nothing else depends on it.
- **Quality:** an analyst reviews a sample of flags each week and records false positives; a rising rate means re-run the evals before changing the prompt.
- **Data:** invoice lines only, with IBANs, card numbers and keyword-led account numbers masked by the gateway on every request (`gateway/mask_hook.py`). Amounts, invoice numbers and vendors are not masked. A bare account number with no keyword is not caught, so keep it out of the text.
- **Owner on call:** the mailbox in the registry entry.
