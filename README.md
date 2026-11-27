<!-- FileRank: C -->
# work
work laboratory

## Execution

Run the [Run workflow](../../actions/workflows/run.yml) on the default branch.

| execution | Operation |
| --- | --- |
| `pr_merge.py` | Merge one pull request |
| `branch_delete.py` | Delete the unchanged head of a merged pull request |
| `pr_merge.py - branch_delete.py` | Merge, then delete in the same run |

Supply shared parameters as a JSON object containing `pr_number` and `expected_head_sha` (the full reviewed PR head commit SHA).

The dispatcher validates the full registered execution list before starting. The Run workflow shows separate Merge and Delete jobs; the second job starts only after a successful first job and only for a two-script request. A single-script request runs one job (the unused second job may appear as skipped). The current workflow has two serial job slots; adding further slots requires a workflow change. Branch deletion still applies its own safety checks and may skip deletion. If deletion fails after a successful merge, retry only `branch_delete.py` with the same parameters.

Only the explicitly requested operations run; ordinary PR merges do not automatically trigger branch deletion.

### Chat and scheduled execution

An owner-authored top-level comment on the target PR can request the same workflow without opening the Actions UI:

```text
/execute {"execution":"pr_merge.py - branch_delete.py","expected_head_sha":"<full reviewed PR head SHA>"}
```

Replace the placeholder with the real SHA. The PR number is derived from the comment's PR. Only newly created comments from the repository owner are accepted; edits, other authors and comment-run replays are rejected. The workflow checks out its trusted default-branch commit, not the PR's code.

For scheduled submission, an explicitly owner-authored comment can use the same JSON with the prefix `/queue `. The ChatGPT scheduled task may submit an equivalent `/execute ` comment with a `queue_comment_id` identifying the approval. A queue entry is not itself an execution trigger. The scheduler must verify the author's ID and current PR state/SHA and avoid resubmitting a queue ID already dispatched. Never infer approval from ordinary PR text. Do not automatically retry failed commands; submit a fresh explicit request.
