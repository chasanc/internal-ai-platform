# Using the gateway: example calls by department

The gateway is a LiteLLM proxy that speaks the OpenAI chat format on `POST /v1/chat/completions`. Every tool calls it the same way. Only the prompt, the alias and the output contract differ.

Everything below runs for free against the mock stack (`make up`), but the `mock` alias returns a fixed support-triage reply, so a department tool's reply will fail its contract there. To see a valid department reply you need a real alias, which costs money. See the README before running one.

## The rules every caller follows

1. **Call an alias, never a provider model.** Aliases are in `gateway/litellm.config.yaml`. Each tool's allowed aliases are in its registry file (`registry/tier*/<tool>.yaml`).
2. **Use the tool's own key.** `registry/issue_keys.py` creates one key per tool with its budget and alias allow-list. A key is shown once and the gateway stores only a hash, so `--apply` requires `--out <file>` (a new file, mode 0600, one `tool=key` line each): move it into your secret store and delete it. Tools that already have a key are skipped; to reissue one, delete its key in the gateway first. A key used on an alias outside its allow-list gets a 403. The demo stack accepts the dev master key instead, `sk-dev-only-master`, which you must never reuse elsewhere.
3. **Mask PII first.** `gateway/pii.py` is the masker (emails, cards, phones, addresses, IBANs, account numbers, tax ids). The support service and the Python client apply it before every call. The gateway masks every request again as a safety net (`gateway/mask_hook.py`), so a caller that forgets still does not send these to the provider, but raw text has then already reached the gateway. Amounts and invoice numbers are not masked. Replies are not masked.
4. **Wrap user text in tags and say it is untrusted.** Each prompt tells the model to ignore instructions inside `<input>` (or `<ticket>`).
5. **Validate the reply.** A reply that is not valid JSON for the contract is a failure, not a partial result. Take the fallback path (no write, human handles it), as in ADR 0005.
6. **A human reviews anything that reaches a person.** The tier and `human_check` in each registry file say how much.

## Other languages

`examples/ts/ask.ts` (Node 22.18+), `examples/go/ask.go` (standard library only) and `examples/csharp/Ask.cs` (.NET 10 SDK) are the same client for the department tools, run from the repo root. Each takes `<tool> <alias> <text>`, reads the tool's `prompt.md` and `contract.json`, and exits 0 for a valid reply, 1 for an invalid one and 2 for a failed call (`go run` reports 1 for any non-zero exit, but prints the real status). They do not mask PII themselves (the gateway does, see rule 3), and they do not cover `support-triage`, whose prompt lives in the service.

```
node examples/ts/ask.ts supplier-delay-triage triage-default "A storm closed the port. 2 days late."
go run examples/go/ask.go supplier-delay-triage triage-default "A storm closed the port. 2 days late."
dotnet run examples/csharp/Ask.cs -- supplier-delay-triage triage-default "A storm closed the port. 2 days late."
```

They were run against the mock stack only: each reached the gateway and rejected the fixed triage reply as expected. Nothing runs them in CI.

## Two ways to call it

The Python client (`examples/python/ask.py`) does steps 1 to 5 for you. `--dry-run` prints the request without sending it:

```
uv run python -m examples.python.ask <tool> "<text>" [--alias <alias>] [--dry-run]
```

For `curl`, define this helper once. It takes the prompt file, the alias, the tag and the text. It does not mask PII itself; the gateway masks the request, but prefer text that has none:

```
export GATEWAY_URL=http://localhost:4000 GATEWAY_KEY=sk-dev-only-master
ask() {  # ask <prompt file> <alias> <tag> <text>
  jq -n --rawfile sys "$1" --arg m "$2" --arg t "$3" --arg x "$4" \
    '{model:$m, temperature:0, max_tokens:400,
      messages:[{role:"system",content:$sys},{role:"user",content:("<"+$t+">"+$x+"</"+$t+">")}]}' |
  curl -s "$GATEWAY_URL/v1/chat/completions" -H "Authorization: Bearer $GATEWAY_KEY" \
       -H "Content-Type: application/json" -d @- | jq -r '.choices[0].message.content'
}
```

The reply shapes below come from each tool's `contract.json`. They show the form, not a recorded model run.

## Support (tier 3, human review required)

Normally reached through the webhook (`services/support-triage/`), which masks, calls the gateway and posts a private note. Calling the gateway directly:

```
uv run python -m examples.python.ask support-triage "I was charged twice for my subscription. Please refund the duplicate."
ask services/support-triage/prompts/triage.v3.md triage-default ticket "I was charged twice. Please refund."
```

Alias `triage-default`, falling back to `triage-fallback`. Reply: `{"category": ..., "priority": ..., "needs_human": true|false, "draft_reply": "..."}`.

## Engineering: PR risk summary (tier 2)

```
uv run python -m examples.python.ask pr-risk-summary "Changes the session token lifetime from 1h to 30d and removes a rate limit on /login."
ask tools/pr-risk-summary/prompt.md triage-default input "Changes the session token lifetime from 1h to 30d."
```

Reply: `{"risk": low|medium|high, "needs_security_review": true|false, "summary": "..."}`. Feed it a diff summary, not source code with secrets.

## Marketing: campaign brief (tier 1, public data)

```
uv run python -m examples.python.ask marketing-campaign-brief "Launch a spring sale for our laptop range aimed at students."
ask tools/marketing-campaign-brief/prompt.md drafts-default input "Spring sale for students, 20% off."
```

Alias `drafts-default`, falling back to `drafts-fallback`. Reply: `{"channel": email|social|search|events, "needs_claims_review": true|false, "brief": "..."}`. When `needs_claims_review` is true, legal checks the claims before anything goes out.

## Finance: invoice anomaly (tier 3, financial data, sampled review)

```
uv run python -m examples.python.ask finance-anomaly "INV-1003 Cleaning. Vendor ShinyCo (known). Amount 310.00. INV-1003 with the same amount was paid on 3 March."
ask tools/finance-anomaly/prompt.md analysis-default input "INV-1003 Cleaning. Vendor ShinyCo (known). Amount 310.00."
```

Alias `analysis-default` (the larger model, no fallback, 60 s timeout). Reply: `{"anomaly": none|duplicate|amount_outlier|unknown_vendor, "hold_payment": true|false, "note": "..."}`. It flags, and a person decides whether to hold a payment. Finance reviews a sample of results.

## People: job description draft (tier 2)

```
uv run python -m examples.python.ask hr-jd-drafts "Senior backend engineer, Python, 5+ years, owns the payments service, hybrid in Berlin."
ask tools/hr-jd-drafts/prompt.md drafts-default input "Senior backend engineer, Python, hybrid in Berlin."
```

Reply: `{"seniority": junior|mid|senior|lead, "flags_biased_wording": true|false, "draft": "..."}`. Never send candidate data through this tool. It is for role descriptions.

## Supply: supplier delay triage (tier 2)

```
uv run python -m examples.python.ask supplier-delay-triage "A storm closed the port. Your shipment will be 2 days late."
ask tools/supplier-delay-triage/prompt.md triage-default input "A storm closed the port. Shipment 2 days late."
```

Reply: `{"cause": weather|customs|production|capacity|unknown, "severity": low|medium|high, "reply": "..."}`. The reply is a draft acknowledgement for the planner to edit. It never agrees to new terms.

## When a call fails or the reply is invalid

- **Gateway error or timeout:** the router retries once, then falls back to the second alias where one is configured (`triage-*`, `drafts-*`). Past that, the call raises. Treat it as the fallback path.
- **Invalid reply:** `examples.python.ask` exits 1 and prints the raw reply. The tool takes the fallback path.
- **Budget exceeded or alias not allowed for your key:** the gateway returns an HTTP error. Ask the tool owner in the registry file to raise the budget or add the alias through a reviewed change.

## Adding your own department

Copy `tools/supplier-delay-triage/` (prompt, `contract.json`, 16-item golden set), add a registry file under the right tier folder, and run `make test`. The registry check validates the new entry. Also add the tool name to `TOOLS` in `examples/python/test_examples.py`, which fails until you do, so every registered tool keeps a tested example.
