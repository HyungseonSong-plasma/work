<!-- FileRank: C -->
# work
work laboratory

## Execution

Run the [Execution workflow](../../actions/workflows/execution.yml) on the default branch.

| execution | Operation |
| --- | --- |
| `pr_merge.py` | Merge one pull request |
| `branch_delete.py` | Delete the unchanged head of a merged pull request |
| `pr_merge.py - branch_delete.py` | Merge, then delete in the same run |

Supply shared parameters as a JSON object containing `pr_number` and `expected_head_sha` (the full reviewed PR head commit SHA).

The dispatcher validates the registered execution list before starting, executes in order, and stops at the first nonzero exit. Branch deletion still applies its own safety checks and may skip deletion. If deletion fails after a successful merge, retry only `branch_delete.py` with the same parameters.

Only the explicitly requested operations run; ordinary PR merges do not automatically trigger branch deletion.
