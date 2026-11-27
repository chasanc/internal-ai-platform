# ADR 0003: A git registry, not a developer portal

Status: accepted (2026-11-27).

## Context

We need one list of AI tools with an owner, the data they touch, their models, a budget and a runbook, so reviews and key issuing have one source of truth.

## Decision

Keep the registry as **YAML files in git**, one per tool, in `registry/tier{1,2,3}/`. A check (`python -m registry.registry_check`) runs in CI.

- The **tier is derived**, not chosen: base from the data class (public 1, internal 2, personal 3, financial 3), raised one tier when no human reviews the output.
- The check requires: folder equals tier, name equals filename, runbook exists, model aliases exist in the gateway config, and a CODEOWNERS rule per tier directory.
- Higher tiers need more approvers through CODEOWNERS. Gateway keys are issued from the registry (`issue_keys.py`, dry run by default).

## Why

- Review, history, blame and approvals already exist in git. A tool change is a pull request.
- Rules are code and are tested; a portal's catalog would need the same checks bolted on.
- Nothing to host, secure or keep in sync.

## Why not Backstage or similar

It adds a service, plugins and an upgrade burden to hold about a dozen entries. Revisit when there are many teams that want self-service pages, search or dependency graphs. The YAML can be imported into such a catalog later.

## Consequences

- No UI; people read files or a generated list.
- CODEOWNERS only works if branch protection requires code-owner review. That setting lives outside the repo and must be checked.
