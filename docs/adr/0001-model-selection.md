# ADR 0001: Model selection for support-triage

Status: accepted (2026-11-27). Revisit when the golden set grows or a candidate model changes.

## Context

`support-triage` classifies a ticket (category, priority, needs_human) and drafts a reply. Tools call a gateway alias, never a provider model name, so the model behind the alias must be chosen on evidence and be easy to change.

We need a repeatable way to answer: *which model should the alias point at, and how do we know a swap did not make things worse?*

## Decision

1. **Choose the cheapest model that passes the gate.** Accuracy first, then cost, then latency, among models that meet the floors below. Do not pay for a larger model without a measured, significant gain.
2. **Score fields, not prose.** Category, priority and `needs_human` are compared to labels. The reply text is not scored by similarity: a good draft can differ from any reference.
3. **Invalid output counts as wrong.** A reply that is not one valid JSON object, or has an unknown category, is a fallback case and scores zero on every field. Schema compliance is reported on its own.
4. **Pin a dated model behind the alias.** The alias moves only after the candidate passes the gate on the same golden set.
5. **Gate on significance, not raw deltas.** A candidate fails if schema compliance < 0.95, category accuracy < 0.70, or category accuracy is significantly worse than the committed baseline (paired exact McNemar, p < 0.05).

Current baseline: `anthropic/claude-haiku-5-5` (`evals/baselines/support-triage.json`).

## Evidence (50 synthetic tickets, single run, 2026-11-27)

| model | category | priority | needs_human | schema | p95 s | $/ticket |
|---|---|---|---|---|---|---|
| claude-haiku-5-5 | 0.98 | 0.72 | 0.92 | 1.00 | 1.7 | 0.000102 |
| claude-sonnet-5-5 | 0.98 | 0.70 | 0.94 | 1.00 | 2.4 | 0.001969 |
| gpt-5.4-mini-2026-03-17 | 0.94 | 0.54 | 0.94 | 1.00 | 1.3 | 0.000421 |
| gpt-5.5-2026-04-23 | 0.98 | 0.56 | 0.94 | 1.00 | 3.7 | 0.004791 |

Paired category tests: no pair differs significantly (smallest p = 0.5).

What this shows:
- On category, the cheap Anthropic model matches the expensive models at about 5% of Sonnet's cost and 2% of gpt-5.5's.
- Priority is the weakest field for every model, and the two OpenAI models score about 16 points lower than the Anthropic ones. Part of this is label subjectivity (what counts as "high" vs "normal"), so priority is **not** in the gate yet.
- Latency differences are small next to a human agent's reading time; none is near a timeout.

## Update: prompt v2 with a priority rubric (2026-11-27)

Priority was the weakest field because the v1 prompt gave no definition of "high" vs "normal". I wrote an explicit rubric into `triage.v2.md` and fixed two labels that broke it (t014, t037). Same four models, same 50 tickets:

| model | category | priority | needs_human | schema | $/ticket |
|---|---|---|---|---|---|
| claude-haiku-5-5 | 0.96 | 0.86 | 0.90 | 1.00 | 0.000141 |
| claude-sonnet-5-5 | 0.98 | 0.84 | 0.90 | 0.98 | 0.002686 |
| gpt-5.4-mini-2026-03-17 | 0.90 | 0.82 | 0.84 | 1.00 | 0.000539 |
| gpt-5.5-2026-04-23 | 0.98 | 0.84 | 0.90 | 1.00 | 0.005316 |

- Priority rose 10-30 points for every model, and the gap between providers closed. The earlier gap was a missing definition, not model quality.
- **Caution:** the rubric was written after reading these labels, so some of the gain is fitting this set. Treat 0.82-0.86 as an upper estimate until the rubric is checked on tickets it was not written from.
- Category and `needs_human` moved by a few points, mostly within noise. The largest drop is gpt-5.4-mini `needs_human` (0.94 to 0.84); the rubric text may be pulling it. Not investigated.
- Priority is still **not** gated. A 20-ticket held-out set (`evals/datasets/support-triage.heldout.jsonl`) was run once on haiku with prompt v2: priority 0.90 (95% interval 0.70 to 0.97), category 0.95, needs_human 1.00, schema 1.00. That supports the rubric, but the interval is wide and the same author wrote these labels after the rubric, so it is not independent evidence. Gate priority only after a larger set labelled by someone else.
- Baseline is now the haiku v2 result. The decision (cheapest model that passes) is unchanged.

## Update: prompt v3 with an optional account line (2026-11-27)

v3 keeps every v2 rule and adds an optional account line (plan, order status, last invoice) that may only inform priority and `needs_human` and must never be copied into the draft. Same four models, same 50 tickets, one run each:

| model | category | priority | needs_human | schema | $/ticket |
|---|---|---|---|---|---|
| claude-haiku-5-5 | 0.98 | 0.90 | 0.90 | 1.00 | 0.000156 |
| claude-sonnet-5-5 | 0.96 | 0.84 | 0.86 | 0.96 | 0.002976 |
| gpt-5.4-mini-2026-03-17 | 0.92 | 0.84 | 0.84 | 1.00 | 0.000671 |
| gpt-5.5-2026-04-23 | 0.96 | 0.86 | 0.92 | 1.00 | 0.006159 |

- No paired category difference against v2 is significant for any model (every p = 1.0; at most one ticket moved). Moves of a few points are noise at n = 50. Sonnet returned 2 invalid replies (schema 0.96), v2 had 1; not investigated.
- Held-out set (20 tickets, haiku): category 0.95, priority 0.85 (v2: 0.90, one ticket), needs_human 1.00, schema 1.00.
- Account set (12 tickets with an account line, haiku): category 0.83, priority 0.83, needs_human 0.83, schema 0.92 (a010, the wrong-invoice-amount case, returned an invalid reply), `account_leaks` 0 of 12. Twelve cases cannot show the account line helps; they show no draft repeated an account value, which is the safety property. This set is not gated.
- These calls go straight to the providers. The gateway, the account lookup and the helpdesk were not in the loop.
- Baseline is now the haiku v3 result (the service runs v3). The decision (cheapest model that passes) is unchanged.

## Why 50 tickets, and what it cannot tell us

With n = 50 a measured accuracy near 0.95 has a 95% interval of roughly ±8 points (Wilson), and wider near 0.5. So:
- The set catches a clearly worse model (accuracy collapse, broken JSON).
- It cannot separate models within a few points. "No significant difference" means *not shown to differ*, not *equal*.
- Rare categories have only a handful of examples, so per-class numbers are indicative.

That is why the gate uses a paired test plus absolute floors rather than "accuracy must not drop": at n = 50, one ticket is 2 points of pure noise. If decisions need to resolve 2-point differences, grow the set (about 1,000 tickets for ±3 points) before trusting the gate for that.

## Known limits

- **Single run.** Some models reject `temperature=0`, so those run at their default and results vary run to run. Repeat runs and report the spread before trusting a close call.
- **Synthetic, hand-labelled data.** Labels reflect one author's judgement. A production set should come from real tickets labelled by agents, with a second labeller on a sample.
- **Reply quality is unscored.** Draft quality needs a rubric reviewed by a human sample; an LLM judge is a later option and must first be checked against human labels (see ADR 0004).
- **Prices and model IDs change.** Costs come from LiteLLM's price table at run time.

## Consequences

- Swapping models is a config change plus `make gate`; the evidence is a result file in git.
- The baseline file must be updated deliberately, in the same PR as the model or prompt change, so the diff shows what moved.
- Priority labels and prompt should be reviewed before priority is gated.

## Alternatives considered

- **Always the largest model:** no measured accuracy gain here, 20-50x the cost.
- **Prose similarity to a reference reply:** rewards matching wording, not correct triage.
- **Raw accuracy threshold relative to baseline:** flaky at n = 50; rejected for the paired test.
