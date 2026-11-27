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

An owner-authored top-level comment on the target PR can request execution without opening the Actions UI. The literal delimiter ` - ` routes to Serial Run; otherwise Single Run handles the request. Both workflows receive the comment event, but only the matching workflow executes a job (the other appears skipped). Python independently validates the full chain and expected script count:

```text
/execute {"execution":"pr_merge.py - branch_delete.py","expected_head_sha":"<full reviewed PR head SHA>"}
```

Replace the placeholder with the real SHA. The PR number is derived from the comment's PR. Only newly created comments from the repository owner are accepted; edits, other authors and comment-run replays are rejected. The workflow checks out its trusted default-branch commit, not the PR's code.

For scheduled submission, an explicitly owner-authored comment can use the same JSON with the prefix `/queue `. The ChatGPT scheduled task may submit an equivalent `/execute ` comment with a `queue_comment_id` identifying the approval. A queue entry is not itself an execution trigger. The scheduler must verify the author's ID and current PR state/SHA and avoid resubmitting a queue ID already dispatched. Never infer approval from ordinary PR text. Do not automatically retry failed commands; submit a fresh explicit request.
