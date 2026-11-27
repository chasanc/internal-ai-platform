# competitor-digest runbook

Reads text crawled from public competitor pages and returns a change type, a `notable` flag and a two or three sentence digest. A scheduler or automation platform crawls and delivers; this tool only summarises. Nothing here crawls or sends.

- **Stop it:** revoke its gateway key (`competitor-digest`).
- **Quality:** a marketer reads a sample of digests against the source pages each week. Wrong prices or invented facts are the failure to look for. Delivery is automatic, so a wrong digest reaches people before anyone checks it; that is why the digest says only what the page says.
- **Evaluation:** 2026-11-27, haiku on the 16-item golden set: 16/16 valid, `change` and `notable` both 16/16, $0.00125 (`evals/results/tool-competitor-digest-haiku.json`). Small self-written set; digest text was not checked for invented facts. Re-run: `uv run python -m evals.tools competitor-digest <litellm model>`.
- **Data:** public pages only. Page text is untrusted: the prompt tells the model to ignore instructions inside it, and the golden set includes injection cases.
- **Crawling:** the owner of the crawl checks each site's terms of use and robots.txt. This repo does not.
- **Owner on call:** the mailbox in the registry entry.
