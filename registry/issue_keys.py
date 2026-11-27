"""Create one gateway key per registry tool, with its budget and model allow-list.

Runs after merge to main. Dry run by default (prints what it would create, no network):
    python -m registry.issue_keys            # dry run
    python -m registry.issue_keys --apply --out keys.txt   # needs LITELLM_URL and LITELLM_MASTER_KEY

LiteLLM shows a new key once and stores only a hash, so --apply requires --out: a new file (never overwritten, mode
0600) with one `tool=key` line per key. Move it into your secret store and delete it. A tool whose alias already has
a key is skipped, so a repeat run is safe; to reissue one, delete its key in the gateway first.
"""
import os
import sys
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).parent.parent


def load_tools(root: Path = ROOT) -> list[dict]:
    return [yaml.safe_load(p.read_text()) for p in sorted((root / "registry").glob("tier*/*.yaml"))]


def key_request(tool: dict) -> dict:
    """Body for LiteLLM's /key/generate."""
    return {
        "key_alias": tool["name"],
        "models": tool["allowed_models"],
        "max_budget": tool["budget_usd_month"],
        "budget_duration": "30d",
        "metadata": {"owner": tool["owner"], "tier": tool["tier"]},
    }


def issue(tool: dict, url: str, master_key: str, client: httpx.Client | None = None) -> str:
    """Returns the new key. The caller must put it in a secret store; never log it.
    shortcut: no rotation or revoke; a repeat call hits LiteLLM's unique key_alias and fails loudly."""
    r = (client or httpx).post(f"{url.rstrip('/')}/key/generate", json=key_request(tool),
                               headers={"Authorization": f"Bearer {master_key}"}, timeout=30)
    r.raise_for_status()
    return r.json()["key"]


def existing_aliases(url: str, master_key: str, client: httpx.Client | None = None) -> set[str]:
    """Aliases of keys the gateway already has. LiteLLM keeps only a hash, so a key cannot be read back later."""
    aliases, page, pages = set(), 1, 1
    while page <= pages:
        r = (client or httpx).get(f"{url.rstrip('/')}/key/list", params={"return_full_object": "true", "size": 100, "page": page},
                                  headers={"Authorization": f"Bearer {master_key}"}, timeout=30)
        r.raise_for_status()
        body = r.json()
        aliases |= {k["key_alias"] for k in body["keys"] if isinstance(k, dict) and k.get("key_alias")}
        pages, page = body.get("total_pages", 1), page + 1
    return aliases


def main(argv: list[str]) -> int:
    tools = load_tools()
    if "--apply" not in argv:
        for t in tools:
            print(f"dry run: would create key {key_request(t)}")
        return 0
    if "--out" not in argv or argv.index("--out") + 1 >= len(argv):
        print("--apply needs --out <file>: the new keys are shown only once, so they must be saved", file=sys.stderr)
        return 2
    out = argv[argv.index("--out") + 1]
    url, master = os.environ["LITELLM_URL"], os.environ["LITELLM_MASTER_KEY"]
    have = existing_aliases(url, master)
    todo = [t for t in tools if t["name"] not in have]
    for t in tools:
        if t["name"] in have:
            print(f"skipped {t['name']}: a key with this alias exists (delete it in the gateway to reissue)")
    if not todo:
        return 0
    # O_EXCL: never overwrite an earlier file; 0600: owner only. Each key is written as soon as it exists, so a
    # failure half way does not lose the ones already issued.
    with os.fdopen(os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as f:
        for t in todo:
            f.write(f"{t['name']}={issue(t, url, master)}\n")
            f.flush()
            print(f"issued key for {t['name']} -> {out}")
    print(f"move {out} into your secret store, then delete it")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
