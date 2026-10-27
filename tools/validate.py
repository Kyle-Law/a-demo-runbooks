"""Validate every runbook: the JSON Schema plus what a schema can't express.

  python tools/validate.py [runbooks/*.yaml]

Exit status 1 if any runbook is invalid. CI runs it on every PR; the executor runs the same checks
before it loads a runbook (B15), so an invalid runbook is never executable.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema/runbook.schema.json").read_text())
TEMPLATE_VARS = {"cluster", "namespace", "kind", "name"}  # filled from the ticket's alert contract


def problems(path: Path) -> list[str]:
    try:
        doc = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        return [f"not valid YAML: {exc}"]
    found = [f"{'/'.join(map(str, e.absolute_path)) or '(top)'}: {e.message}"
             for e in jsonschema.Draft202012Validator(SCHEMA).iter_errors(doc)]
    if found:
        return found  # the checks below assume the schema holds
    if doc["id"] != path.stem:
        found.append(f"id '{doc['id']}' must equal the file name '{path.stem}'")
    for var in sorted(set(re.findall(r"\{\{\s*(\w+)\s*\}\}", path.read_text())) - TEMPLATE_VARS):
        found.append(f"unknown template variable {{{{{var}}}}}; allowed: {sorted(TEMPLATE_VARS)}")
    if "resource" in doc["matches"]:
        try:
            re.compile(doc["matches"]["resource"])
        except re.error as exc:
            found.append(f"matches.resource is not a valid regex: {exc}")
    return found


def main(paths: list[str]) -> int:
    files = [Path(p) for p in paths] or sorted((ROOT / "runbooks").glob("*.yaml"))
    failed, ids = False, {}
    for f in files:
        errs = problems(f)
        doc_id = (yaml.safe_load(f.read_text()) or {}).get("id") if not errs else None
        if doc_id in ids:
            errs.append(f"duplicate id '{doc_id}' (also in {ids[doc_id].name})")
        if doc_id:
            ids[doc_id] = f
        for e in errs:
            print(f"FAIL {f.relative_to(ROOT) if f.is_absolute() else f}: {e}")
        failed |= bool(errs)
        if not errs:
            print(f"ok   {f.relative_to(ROOT) if f.is_absolute() else f}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
