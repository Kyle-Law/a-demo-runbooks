"""The validator accepts the runbooks in this repo and rejects what must never become executable."""
import copy
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import validate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
GOOD = yaml.safe_load((ROOT / "runbooks/pod-unschedulable.yaml").read_text())
# A copy of a-demo's platform/vault/runbook-roles.yaml; CI also checks against the live one on main.
ROLES = validate.load_vault_roles(str(ROOT / "tests/fixtures/runbook-roles.yaml"))


def test_every_runbook_in_the_repo_is_valid():
    assert validate.main([], roles=ROLES) == 0


def write(tmp_path, doc, name="pod-unschedulable"):
    p = tmp_path / f"{name}.yaml"
    p.write_text(yaml.safe_dump(doc))
    return p


@pytest.mark.parametrize("mutate, expected", [
    (lambda d: d["steps"].append({"action": "shell", "command": "kubectl delete ns inference"}), "steps"),
    (lambda d: d["steps"][0].update(force=True), "steps"),
    (lambda d: d.pop("verify"), "verify"),
    (lambda d: d.pop("rollback"), "rollback"),
    (lambda d: d.update(requires_approval="yes"), "requires_approval"),
    (lambda d: d["matches"].update(signals=[]), "signals"),
    (lambda d: d["verify"][0].update(expect="maybe"), "expect"),
    (lambda d: d["preconditions"][0].update(promql='up{cluster="{{env}}"}'), "unknown template variable"),
    (lambda d: d["matches"].update(resource="^pod/(unclosed"), "regex"),
])
def test_rejected(tmp_path, mutate, expected):
    doc = copy.deepcopy(GOOD)
    mutate(doc)
    errs = validate.problems(write(tmp_path, doc))
    assert errs and any(expected in e for e in errs), errs


def test_id_must_match_file_name(tmp_path):
    errs = validate.problems(write(tmp_path, copy.deepcopy(GOOD), name="something-else"))
    assert any("must equal the file name" in e for e in errs)


@pytest.mark.parametrize("mutate, expected", [
    (lambda d: d.update(required_role="cluster-admin"), "not a role Vault can mint"),
    (lambda d: d["matches"].pop("clusters"), "limit matches.clusters"),          # c3 too, role is c1/c2 only
    (lambda d: d["matches"].update(clusters=["c1", "c3"]), "limit matches.clusters"),
    (lambda d: d["steps"][0].update(namespace="kube-system"), "namespace 'kube-system'"),
    (lambda d: d.update(steps=[{"action": "argocd.sync", "app": "models-c1"}]), "argocd.* actions run on c3"),
])
def test_rejected_against_vault_roles(tmp_path, mutate, expected):
    doc = copy.deepcopy(GOOD)
    mutate(doc)
    errs = validate.problems(write(tmp_path, doc), ROLES)
    assert errs and any(expected in e for e in errs), errs


def test_role_check_is_skipped_only_when_asked(tmp_path):
    doc = copy.deepcopy(GOOD)
    doc["required_role"] = "cluster-admin"
    path = write(tmp_path, doc)
    assert validate.main([str(path)], roles=ROLES) == 1
    assert validate.main(["--no-vault-roles", str(path)]) == 0


def test_unreadable_roles_fail_closed(tmp_path):
    assert validate.main(["--vault-roles", str(tmp_path / "missing.yaml")]) == 1
