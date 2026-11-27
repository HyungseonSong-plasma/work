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

The repository-root `github/model.py` is the shared GitHub REST API transport and workflow dispatch module. Execution and routing policies remain in `scripts/`. The root `app/` package provides the only command-line entry point; `scripts/` contains importable task and routing functions. Workflows use `python3 -m app` from the trusted repository root, so no PYTHONPATH override is necessary.

### Unified CLI

```sh
python3 -m app --help
python3 -m app trigger
python3 -m app execute --single
python3 -m app execute --serial-stage 1
python3 -m app execute --serial-stage 2
```

These commands consume the existing GitHub event and execution environment variables. The dispatcher launches registered tasks as isolated `python3 -m app task <script>` subprocesses, with a fixed allowlist and fail-fast exit handling. Task is a low-level command; for workflow execution use `execute`, which validates the whole chain before starting. Serial stage ordering remains enforced by GitHub Actions `needs`; invoking stage 2 manually does not establish stage 1 success. The existing branch deletion policy still requires an already merged PR.
