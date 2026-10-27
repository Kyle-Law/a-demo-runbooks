"""Validate every runbook: the JSON Schema plus what a schema can't express.

  python tools/validate.py [--vault-roles PATH_OR_URL | --no-vault-roles] [runbooks/*.yaml]

Exit status 1 if any runbook is invalid. CI runs it on every PR; the executor runs the same checks
before it loads a runbook (B15), so an invalid runbook is never executable.

It also checks each runbook against the roles Vault can mint tokens for, listed in a-demo's
platform/vault/runbook-roles.yaml (fetched from a-demo's main by default): the required_role must be
there, and its clusters must cover where the steps act. Otherwise the runbook would merge and then
fail at run time when Vault refuses the token. --no-vault-roles skips this (offline only).
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema/runbook.schema.json").read_text())
TEMPLATE_VARS = {"cluster", "namespace", "kind", "name"}  # filled from the ticket's alert contract
VAULT_ROLES_URL = "https://raw.githubusercontent.com/Kyle-Law/a-demo/main/platform/vault/runbook-roles.yaml"
ALL_CLUSTERS = ["c1", "c2", "c3"]
HUB = "c3"  # argocd.* actions act on the hub, where the Applications live


def load_vault_roles(source: str) -> dict:
    """{role: {clusters, namespaces}} from a-demo's runbook-roles.yaml, by path or URL."""
    if source.startswith("https://"):
        with urllib.request.urlopen(source, timeout=30) as resp:
            text = resp.read().decode()
    else:
        text = Path(source).read_text()
    return yaml.safe_load(text)["roles"]


def role_problems(doc: dict, roles: dict) -> list[str]:
    """Can Vault mint required_role where this runbook's steps act?"""
    role = doc["required_role"]
    if role not in roles:
        return [f"required_role '{role}' is not a role Vault can mint (have: {', '.join(sorted(roles))}); "
                "add it to a-demo's platform/vault/runbook-roles.yaml first"]
    found, have = [], set(roles[role]["clusters"])
    actions = {s["action"] for s in doc["steps"] + doc["rollback"]}
    if any(a.startswith("argocd.") for a in actions) and HUB not in have:
        found.append(f"argocd.* actions run on {HUB}, but role '{role}' is only minted on {sorted(have)}")
    if any(a.startswith("k8s.") for a in actions):
        targets = doc["matches"].get("clusters", ALL_CLUSTERS)
        missing = sorted(set(targets) - have)
        if missing:
            found.append(f"k8s.* actions run on the ticket's cluster, and this runbook matches {sorted(targets)}, "
                         f"but role '{role}' is only minted on {sorted(have)}: limit matches.clusters to those")
    for step in doc["steps"] + doc["rollback"]:
        ns = step.get("namespace")
        if ns and "{{" not in ns and ns not in roles[role]["namespaces"]:
            found.append(f"{step['action']} acts in namespace '{ns}', but role '{role}' is only minted "
                         f"for {roles[role]['namespaces']}")
    return found


def problems(path: Path, roles: dict | None = None) -> list[str]:
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
    if roles is not None:
        found += role_problems(doc, roles)
    return found


def shown(path: Path) -> Path:
    """The path relative to the repo when it's inside it, else as given."""
    return path.relative_to(ROOT) if path.is_absolute() and path.is_relative_to(ROOT) else path


def main(argv: list[str], roles: dict | None = None) -> int:
    args, source = list(argv), VAULT_ROLES_URL
    if "--no-vault-roles" in args:
        args.remove("--no-vault-roles")
        source = None
    if "--vault-roles" in args:
        i = args.index("--vault-roles")
        source = args[i + 1]
        del args[i:i + 2]
    if roles is None and source:
        try:
            roles = load_vault_roles(source)
        except Exception as exc:  # fail closed: an unchecked role must not merge
            print(f"FAIL cannot read Vault roles from {source}: {exc}")
            return 1
    files = [Path(p) for p in args] or sorted((ROOT / "runbooks").glob("*.yaml"))
    failed, ids = False, {}
    for f in files:
        errs = problems(f, roles)
        doc_id = (yaml.safe_load(f.read_text()) or {}).get("id") if not errs else None
        if doc_id in ids:
            errs.append(f"duplicate id '{doc_id}' (also in {ids[doc_id].name})")
        if doc_id:
            ids[doc_id] = f
        for e in errs:
            print(f"FAIL {shown(f)}: {e}")
        failed |= bool(errs)
        if not errs:
            print(f"ok   {shown(f)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
