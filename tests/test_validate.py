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


def test_every_runbook_in_the_repo_is_valid():
    assert validate.main([]) == 0


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
