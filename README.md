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

The repository-root `github/model.py` provides shared GitHub REST API transport, workflow dispatch, and a generic ordered `WorkflowRegistry`. `github/trigger.py` loads the supported workflow routes from `config/workflows.json`, validates GitHub PR comments, and dispatches exactly one matching workflow. The root `app/` package provides the only command-line entry point; `scripts/` contains importable task and execution functions. Workflows use `python3 -m app` from the trusted repository root, so no PYTHONPATH override is necessary.

### Unified CLI

```sh
python3 -m app --help
python3 -m app trigger
python3 -m app execute --single
python3 -m app execute --serial-stage 1
python3 -m app execute --serial-stage 2
```

These commands consume the existing GitHub event and execution environment variables. The dispatcher launches registered tasks as isolated `python3 -m app task <script>` subprocesses, with a fixed allowlist and fail-fast exit handling. Task is a low-level command; for workflow execution use `execute`, which validates the whole chain before starting. Serial stage ordering remains enforced by GitHub Actions `needs`; invoking stage 2 manually does not establish stage 1 success. The existing branch deletion policy still requires an already merged PR.

### Adding CLI commands

`app/cli.py` is a generic parser and dispatcher. To add a command, define a class in `app/commands/` with a help string, `configure(parser)`, and `execute(args)`, decorate it with `@register("command-name")`, explicitly import the module in `app/commands/__init__.py`, and add its name to `config/commands.json`. Duplicate registrations and invalid command interfaces are rejected. No filesystem discovery or user-controlled module imports are used. The CLI command registry is separate from the restricted workflow task allowlist in `scripts/execute.py`.

Run offline regression tests with `python3 -m unittest discover -s tests -v`.

For an end-to-end CLI regression check, use a reviewed documentation-only PR and submit the existing serial execution command. Confirm that Trigger submits exactly one Serial Run, Merge completes before Delete starts, the PR is merged, and its unchanged head branch is absent. Inspect the run logs rather than relying only on the workflow conclusion.

### Adding workflow routes

Register exact ordered script arrays and workflow filenames in `config/workflows.json`. The loader checks each script against `config/executions.json`. `route()` uses the same registry lookup for all chains. Unknown and duplicate routes are rejected. Registration does not create a workflow or grant permission to run new scripts: the corresponding YAML, worker validation, task allowlist and execution contract must also support the route. CLI command registration remains separate.

When verifying a workflow route change, confirm the Trigger and worker runs both use the post-change default-branch commit. A successful merge of the change itself exercises the previous implementation and is not sufficient evidence for the new route registry.

### Registry configuration

The four C-rank JSON registries under `config/` define CLI command names, execution allowlists, ordered workflow routes and deletion availability. Code still binds explicitly imported implementations; JSON cannot import arbitrary modules, create workflow permissions or bypass validation. `config/deletions.json` enables only branch deletion; issue deletion is disabled because the default GITHUB_TOKEN returned FORBIDDEN in the disposable issue #15 probe. Actions Run deletion is also disabled until a dedicated target/permission contract and handler are implemented. The permission strings are documentation, not authorization. No changes to existing YAML or comment protocol are required.
