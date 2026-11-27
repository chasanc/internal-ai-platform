"""Validate the tool registry. CI runs this on every PR: python -m registry.registry_check [repo_root]

Tier rules (one place, so a tool cannot pick its own tier):
  base tier from data:  public=1, internal=2, personal=3, financial=3
  human_check "none" raises it one tier (max 3): unreviewed output is riskier.
"""
import json
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).parent.parent
SCHEMA = json.loads((Path(__file__).parent / "schema.json").read_text())
BASE_TIER = {"public": 1, "internal": 2, "personal": 3, "financial": 3}


def derive_tier(data: str, human_check: str) -> int:
    return min(3, BASE_TIER[data] + (human_check == "none"))


def check(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    validator = Draft202012Validator(SCHEMA)
    config = yaml.safe_load((root / "gateway/litellm.config.yaml").read_text())
    aliases = {m["model_name"] for m in config["model_list"]}
    codeowners = (root / "CODEOWNERS").read_text() if (root / "CODEOWNERS").exists() else ""
    names: dict[str, Path] = {}

    for path in sorted((root / "registry").glob("tier*/*.yaml")):
        rel = path.relative_to(root)
        tool = yaml.safe_load(path.read_text())
        problems = sorted(validator.iter_errors(tool), key=str) if isinstance(tool, dict) else []
        if not isinstance(tool, dict) or problems:
            errors += [f"{rel}: {e.message}" for e in problems] or [f"{rel}: not a mapping"]
            continue
        folder = int(path.parent.name.removeprefix("tier"))
        want = derive_tier(tool["data"], tool["human_check"])
        if tool["tier"] != want:
            errors.append(f"{rel}: tier is {tool['tier']} but data={tool['data']}, human_check={tool['human_check']} gives tier {want}")
        if folder != want:
            errors.append(f"{rel}: file is in tier{folder}/ but the tool is tier {want}; move it")
        if tool["name"] != path.stem:
            errors.append(f"{rel}: name '{tool['name']}' must equal the file name")
        if tool["name"] in names:
            errors.append(f"{rel}: name already used by {names[tool['name']].relative_to(root)}")
        names[tool["name"]] = path
        if not (root / tool["runbook"]).is_file():
            errors.append(f"{rel}: runbook {tool['runbook']} does not exist")
        errors += [f"{rel}: model alias '{a}' is not defined in gateway/litellm.config.yaml"
                   for a in tool["allowed_models"] if a not in aliases]

    for tier_dir in sorted((root / "registry").glob("tier*")):
        if f"/registry/{tier_dir.name}/" not in codeowners:
            errors.append(f"CODEOWNERS has no rule for /registry/{tier_dir.name}/")
    return errors


def main(argv: list[str]) -> int:
    errors = check(Path(argv[0]) if argv else ROOT)
    for e in errors:
        print(f"registry: {e}")
    print("registry: ok" if not errors else f"registry: {len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
