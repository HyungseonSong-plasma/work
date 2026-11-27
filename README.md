<!-- FileRank: C -->
# work
work laboratory

## Execution

Use [Single Run](../../actions/workflows/single_run.yml) for one script or [Serial Run](../../actions/workflows/serial_run.yml) for a dependent chain. Both run on the default branch.

| execution | Operation |
| --- | --- |
| `pr_merge.py` | Merge one pull request |
| `branch_delete.py` | Delete the unchanged head of a merged pull request |
| `pr_merge.py - branch_delete.py` | Merge, then delete in the same run |

Supply shared parameters as a JSON object containing `pr_number` and `expected_head_sha` (the full reviewed PR head commit SHA).

The dispatcher validates the full registered execution list before starting. Single Run has one job (Merge or Delete). Serial Run has two jobs (Merge then Delete); Delete starts only after Merge succeeds. The current serial workflow supports exactly the two registered scripts in that order. Branch deletion still applies its own safety checks and may skip deletion. If deletion fails after a successful merge, retry only `branch_delete.py` with the same parameters in Single Run.

Only the explicitly requested operations run; ordinary PR merges do not automatically trigger branch deletion.

### Chat and scheduled execution

An owner-authored top-level comment on the target PR can request execution without opening the Actions UI. Only Trigger subscribes to PR comments. It validates the owner and the full registered execution list, then submits exactly one workflow_dispatch request to Single Run or Serial Run. The execution workflows no longer subscribe to comments. Trigger reports submission, not execution success; the target run has the source comment ID in its run name. The target workflow independently validates the full chain and expected script count:

```text
/execute {"execution":"pr_merge.py - branch_delete.py","expected_head_sha":"<full reviewed PR head SHA>"}
```

Replace the placeholder with the real SHA. The PR number is derived from the comment's PR. Only newly created comments from the repository owner are accepted; edits, other authors and comment-run replays are rejected. Trigger and the execution workflows check out their trusted default-branch event commits, not the PR's code. Trigger has contents: read and actions: write; only the execution jobs have contents: write. A fresh request is required instead of rerunning a previous run.

For scheduled submission, an explicitly owner-authored comment can use the same JSON with the prefix `/queue `. The ChatGPT scheduled task may submit an equivalent `/execute ` comment with a `queue_comment_id` identifying the approval. A queue entry is not itself an execution trigger. The scheduler must verify the author's ID and current PR state/SHA and avoid resubmitting a queue ID already dispatched. Never infer approval from ordinary PR text. Do not automatically retry failed commands; submit a fresh explicit request.

### Inspecting execution results

Open [Trigger](../../actions/workflows/trigger.yml) to inspect request submission, then find the corresponding Single Run or Serial Run by its `comment-<id>` run-name suffix. In Serial Run, inspect Merge and Delete separately. A successful Delete job can also represent a safety skip; verify its log and branch state before reporting that the branch was removed.

### GitHub integration

The repository-root `github/model.py` provides shared GitHub REST API transport, workflow dispatch, and a generic ordered `WorkflowRegistry`. `github/trigger.py` loads the supported workflow routes from `config/workflows.toml`, validates GitHub PR comments, and dispatches exactly one matching workflow. The root `app/` package provides the only command-line entry point; `scripts/` contains importable task and execution functions. Workflows use `python3 -m app` from the trusted repository root, so no PYTHONPATH override is necessary.

### Unified CLI

```sh
python3 -m app --help
python3 -m app trigger
python3 -m app execute --single
python3 -m app execute --serial-stage 1
python3 -m app execute --serial-stage 2
python3 -m app test
```

These commands consume the existing GitHub event and execution environment variables. The dispatcher launches registered commands as isolated `python3 -m app merge` or `python3 -m app delete branch` subprocesses, with a fixed allowlist and fail-fast exit handling. `app/commands/model.py` provides the common command binding, event validation, PR context and result reporting; `app/registry.py` projects its single registry onto the exact execution allowlist. The former `task.py` and `TASKS` registry are removed. For workflow execution use `execute`, which validates the whole chain before starting. Serial stage ordering remains enforced by GitHub Actions `needs`; invoking stage 2 manually does not establish stage 1 success. The existing branch deletion policy still requires an already merged PR.

### Adding CLI commands

`app/cli.py` is a generic parser and dispatcher. To add a command, define a subclass of `Command` from `app/commands/model.py` in `app/commands/` with a help string, `configure(parser)`, and `execute(args)`, decorate it with `@register("command-name")`, explicitly import the module in `app/commands/__init__.py`, and add its name to `config/commands.toml`. Duplicate registrations and invalid command interfaces are rejected. No filesystem discovery or user-controlled module imports are used. Only commands with an explicit `workflow_execution` tuple can be selected by the restricted workflow allowlist. Unknown, duplicate or missing execution bindings fail closed. CLI registration alone grants no workflow eligibility.

Run offline regression tests with `python3 -m app test`.

For an end-to-end CLI regression check, use a reviewed documentation-only PR and submit the existing serial execution command. Confirm that Trigger submits exactly one Serial Run, Merge completes before Delete starts, the PR is merged, and its unchanged head branch is absent. Inspect the run logs rather than relying only on the workflow conclusion.

### Adding workflow routes

Register exact ordered script arrays and workflow filenames in `config/workflows.toml`. The loader checks each script against `config/executions.toml`. `route()` uses the same registry lookup for all chains. Unknown and duplicate routes are rejected. Registration does not create a workflow or grant permission to run new scripts: the corresponding YAML, worker validation, task allowlist and execution contract must also support the route. CLI command registration remains separate.

When verifying a workflow route change, confirm the Trigger and worker runs both use the post-change default-branch commit. A successful merge of the change itself exercises the previous implementation and is not sufficient evidence for the new route registry.

### Registry configuration

The C-rank TOML registries under `config/` define CLI command names, execution allowlists, ordered workflow routes, deletion availability and test suites. Python 3.11 or newer is required for the standard-library `tomllib` parser. Code still binds explicitly imported implementations; TOML cannot import arbitrary modules, create workflow permissions or bypass validation. `config/deletions.toml` enables branch and Actions Run deletion; issue deletion remains disabled because the default GITHUB_TOKEN returned FORBIDDEN in the disposable issue #15 probe. The permission strings are documentation, not authorization. The existing execution YAML and comment protocol remain unchanged. The `/execute` and `/queue` request protocol and GitHub API payloads remain JSON.

For TOML registry regression verification, confirm that the worker and Trigger use the same reviewed configuration commit and that the serial route is selected from `config/workflows.toml`.

### Test registry

The offline test suite uses `config/tests.toml` as its ordered manifest. Each `tests/suites/` module registers a subclass of `TestSuite` from `tests/suites/model.py` with `@register(name)` from `tests/registry.py`; `tests/suites/__init__.py` imports implementations explicitly. The registered CLI command `app/commands/test.py` lazily imports the suites and builds the configured suite. Shared deterministic fixtures and common contract helpers live in `tests/suites/model.py`. Missing, unknown, duplicate or empty suites are rejected instead of silently reducing coverage. Keep fixtures and assertions independent of production registry data. Run the full suite with the `python3 -m app test` command. To extend tests, add a registered suite and its manifest entry; no dispatcher conditionals or dynamic imports are required.

Verify the TOML serial route with a documentation-only PR on the post-migration default branch; confirm both job conclusions and actual branch removal.

The command model supplies default argument configuration, abstract execute contract, parser binding, event validation, repository and PR context and shared result reporting. Registries remain responsible for explicit registration, manifest loading and validation, not implementation details. Command modules follow the same layout: module-level execution logic first, followed by a thin registered Command subclass containing metadata, argument configuration where needed, and a single delegation to the module-level execute function. Shared Actions authorization/context validation lives in app/commands/model.py; branch and Actions deletion keep their separate target checks.

### GitHub deletion framework

`github/delete.py` exposes `delete(target, **parameters)` backed by explicitly registered branch and Actions handlers. The old `scripts/branch_delete.py` is an inert compatibility marker for existing approved PR execution chains; all deletion logic is in `github/delete.py`. Shared PR parameter parsing and HTTP 204 deletion transport live in `github/model.py`.

Actions Run deletion is available through an owner-authored PR comment or manual dispatch of [Delete Actions Run](../../actions/workflows/actions_delete.yml), with the exact reviewed run ID, full head SHA and run attempt. The workflow runs on the default branch, first attempt only. Manual dispatch requires the owner; a Trigger dispatch must cite the exact unchanged owner PR comment, which the worker re-fetches and validates against the inputs. The workflow has `actions: write` and `contents: read`, not `contents: write`; existing merge/delete workers retain their original permissions. Only completed runs in this repository may be deleted. The current run, pinned evidence IDs, and the newest successful run(s) for each listed audit workflow are retained according to config/actions_policy.toml. Explicit batches are limited to 30 reviewed targets. No automatic age-based cleanup is implemented. Each batch preflights all targets, then revalidates and deletes sequentially; later errors stop the batch but cannot restore earlier deletions. Metadata is rechecked immediately before DELETE, but the GitHub endpoint does not offer an atomic attempt guard; do not rerun a target concurrently. The controller remains submission-only for the original PR execution chains; it cannot submit Actions deletion. The separate owner PR comment route is `/execute {"execution":"delete actions","run_id":123,"expected_head_sha":"<full run head SHA>","expected_run_attempt":1}`. No queue_comment_id is accepted. The isolated deletion workflow also receives issues: read and pull-requests: read to verify the source comment and PR; existing workers are unchanged.

After changing the shared deletion framework, verify the legacy branch execution marker still dispatches to the registered GitHub branch handler in a post-change serial run.

Batch comment: `/execute {"execution":"delete actions","runs":[{"run_id":123,"expected_head_sha":"<full SHA>","expected_run_attempt":1}]}`. The original single-run format remains supported. Never use implicit selectors. Only one deletion workflow may execute at a time; GitHub may replace pending concurrency-group runs, so submit one batch at a time.

The approved external execution IDs `pr_merge.py` and `branch_delete.py` remain unchanged, as do workflow YAML, permissions, comment syntax and the Controller queue allowlist. Branch and Actions deletion share DeleteCommand but keep independent authorization and target validation; only branch deletion is eligible for PR execution chains.

Post-refactor live verification uses the unchanged serial PR comment contract to launch the registered merge and delete branch commands via the unified registry.

After standardizing the thin command adapters, verify the unchanged serial comment route and the dedicated Actions deletion context through the post-change default branch.
