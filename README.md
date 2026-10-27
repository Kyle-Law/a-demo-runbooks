# a-demo-runbooks

Reviewed remediations for the [a-demo](https://github.com/Kyle-Law/a-demo) GPU platform. The executor (a-demo
B15) runs a runbook from this repo's **merged `main`** when an alert ticket matches it. A human approves on the
Jira ticket when `requires_approval` is set, and the executor uses a short-lived Vault token scoped to the
runbook's `required_role`.

This repo is separate from a-demo so the ops agent's GitHub token (B16: the agent proposes new runbooks as PRs)
reaches **only** this repo (a-demo CLAUDE.md decision 8). An agent-authored runbook is never executable until a
human merges it (decision 7): the executor reads only `main`, `main` is protected, and every change needs a
code-owner review.

## A runbook

```yaml
apiVersion: a-demo.io/v1
id: model-server-down                 # = file name = the alert's runbook_hint
title: Restore a crash-looping model server from Git
matches:
  signals: [ModelServerDown]          # alert signal(s) it handles
  resource: "^deployment/.+-vllm$"    # optional regex on the ticket's resource
required_role: gitops-operator        # Vault role: bounds what the steps can do
requires_approval: true               # a human /approve on the Jira ticket first
preconditions: [...]                  # read-only PromQL checks; all must pass
steps: [...]                          # typed actions (below), never shell
verify: [...]                         # must pass within `within`, or rollback runs
rollback: [...]
```

Templates: `{{cluster}}`, `{{namespace}}`, `{{kind}}`, `{{name}}` come from the ticket's alert contract
(`resource: deployment/model-b-vllm` → kind `deployment`, name `model-b-vllm`). Checks are PromQL on the hub
Prometheus, with `expect: empty | nonempty`.

**Actions** are a closed vocabulary that the executor implements. Each needs only a narrow permission:

| Action | Does | Needs |
|---|---|---|
| `argocd.resume_autosync` `{app}` | turns Argo CD auto-sync (prune + self-heal) back on | patch Applications (C3) |
| `argocd.sync` `{app}` | syncs the Application to Git | patch Applications (C3) |
| `k8s.delete_unowned_pod` `{namespace, name}` | deletes a pod, **refusing** if any controller owns it | get + delete pods |
| `k8s.delete_jobs` `{namespace, label_selector}` | deletes the Jobs matching the selector | list + delete jobs |
| `k8s.rollout_restart` `{namespace, deployment}` | restarts a Deployment's pods | patch deployments |
| `notify` `{message}` | comments on the ticket | — |

## Runbooks

| Runbook | Fault (a-demo `chaos/`) | Fix |
|---|---|---|
| `model-server-down` | `model-server-crashloop.sh` | resume Argo CD auto-sync + sync: Git restores the Deployment |
| `pod-unschedulable` | `gpu-claim-pending.sh` | delete the stray pod, refused if anything owns it |
| `inference-queue-backlog` | `inference-queue-backlog.sh` | delete `load-class=batch` Jobs |

`NodeNotReady` has no runbook on purpose. Fixing it needs host access, which no Kubernetes-scoped token gives, so
the executor escalates to a human. It's a good first candidate for the agent to propose a runbook (B16).

## Validate

```bash
pip install -r requirements-dev.txt
python tools/validate.py && pytest -q tests
```

`tools/validate.py` applies `schema/runbook.schema.json` and the checks a schema can't express: `id` = file
name, only known template variables, valid regexes, unique ids. CI runs it on every PR.
