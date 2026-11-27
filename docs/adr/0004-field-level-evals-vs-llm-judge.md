# ADR 0004: Field-level evals, not LLM-as-judge, for the release gate

Status: accepted (2026-11-27).

## Context

A model or prompt change can silently make triage worse. We need an automatic check that blocks a regression before release. Two options: compare structured fields to labels, or ask another model to grade the output.

## Decision

The release gate uses **field-level scoring against human labels**: category, priority and `needs_human` are compared to the label, and an invalid or out-of-contract output counts as wrong. Reply drafts are **not** part of the gate. They are reviewed by a human sample until an automatic scorer is shown to agree with humans.

An LLM judge may be added later for draft quality, as an advisory signal, only after it passes the check below.

## Why

- **Deterministic and cheap.** Same inputs, same score, no extra model call, no judge cost, no judge drift when a provider updates its model.
- **Measures the thing that causes harm.** A wrong category misroutes a ticket. Matching wording or tone is not the failure we need to prevent.
- **Output contract is testable.** Schema compliance and unknown-category handling are exact checks; a judge would blur them.
- **Explainable.** A failure points at specific tickets and fields. A judge score gives a number and a rationale that can itself be wrong.
- **Resistant to manipulation.** Ticket text is untrusted. A judge reading it can be steered by injected instructions; a field comparison cannot.

## Why not prose similarity either

BLEU/ROUGE/embedding similarity to a reference reply rewards matching the old wording. A good draft can differ from any reference, and a bad one can be close. It correlates with accuracy poorly enough that it would pass wrong drafts and fail good ones.

## When an LLM judge is acceptable

Only for open-ended quality (tone, completeness, no invented facts) and only if:

1. A human labels a sample (start with 50 drafts), ideally with two labellers on part of it.
2. The judge's agreement with humans is measured (for example Cohen's kappa) and is close to the humans' agreement with each other.
3. The judge model is pinned and different from the model under test, to avoid self-preference.
4. Results are reported with intervals, as for the field scores.

Until then, drafts are sampled and read by a person, and the live signal is the agent's action (sent, edited, discarded) per prompt version.

## Consequences

- The gate covers triage fields only; draft quality is a known gap, handled by human sampling.
- Labels are the bottleneck. Their quality caps what the gate can detect (see priority labels in ADR 0001).
- If judge agreement is shown, adding it is additive: a new advisory column, not a rewrite.
