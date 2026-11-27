# FileRank: C

# Reproducible offline verification (Q6)

The ordinary offline suite remains `PYTHONPATH=src python3 -m work test`. Use the separate strict snapshot comparison when reviewing behavior-preserving changes. The versioned probes retain the 1,696 historical unique observations, recover one previously overwritten Suite registration duplicate observation (1,697 total), and preserve the 29 post-Q1/Q2 semantic cases from [Q5 CI 46036708411](https://github.com/HyungseonSong-plasma/work/actions/runs/46036708411). The full suite runs separately on each snapshot.

## Run

Use Python 3.11+ and Git on a POSIX host. Use two clean, existing checkouts of **trusted** post-Q1/Q2 revisions of this repository, and the same Python executable for both. Verify both commits before executing their code. For example, from a trusted checkout containing these verification files:

```bash
git worktree add --detach /tmp/work-baseline <baseline-full-sha>
git worktree add --detach /tmp/work-candidate <candidate-full-sha>
python3 tests/verification/compare.py \
  --baseline /tmp/work-baseline --baseline-sha <baseline-full-sha> \
  --candidate /tmp/work-candidate --candidate-sha <candidate-full-sha>
```

Replace placeholders with the reviewed full lowercase 40-character SHAs. The comparator does not fetch, checkout, mutate or remove worktrees. After use, remove them explicitly with `git worktree remove` if appropriate. The child processes use a temporary HOME, fixed hash seed and minimal environment without inherited GitHub credentials; Git status and SHA are checked before and after observations. This is not a security sandbox: trusted snapshots and probe code are mandatory, and ignored files/local Git settings can still affect execution. Run without network access if isolation is required.

The expected gates are successful full suites, original unique test IDs in relative order (new tests permitted), exactly 1,697 unique differential observations with equal keys and values, and 18 Q1 + 11 Q2 semantic observations with equal output and their embedded expected outcomes. Differences fail with a nonzero status. The probes mock mutation transports. The historical case named Q1_fresh_listing_changes_to_inconsistent actually rejects a short preflight page after Q1; the separate durable deletion suite covers valid preflight followed by inconsistent fresh review.

Run comparator self-tests with `python3 -m unittest tests.verification.test_compare`. The runner is not a general equivalence proof or coverage measure. For approved behavior changes, review and version the affected expected observations explicitly; do not bypass differences with an ignore flag. Snapshot-specific architecture/AST or file-change assertions remain separate review gates. These probes are intended for the post-Q1/Q2 contract, not arbitrary older revisions. For D2 comparisons, use the comparator and probe files from the reviewed post-D2 checkout. The fixed test-only namespace selector recognizes exactly one of the historical `libs` or canonical `work.libs` layouts within each verified checkout, rejects missing or ambiguous layouts, and checks the imported probe module path. No production import alias is installed; observation keys, expected values and counts remain unchanged. No automatic or required CI is introduced. 

## D4 source layout transition

Use the comparator from the reviewed src-layout checkout. It selects exact legacy/flat/src paths, verifies probe imports originate from the selected snapshot, and sets the source Python path explicitly. The D4 transition compares all 1697 observations, accepting only the enumerated CLI display-name and child argv changes (child cwd checked against the appropriate trusted root); every other field and observation remains exact. Comparisons within the same layout retain strict equality. Source-only test execution is from the reviewed checkout root. Build/install verification: `python tests/verification/packaging_probe.py` in an environment with the pinned build frontend and access to the reviewed backend wheelhouse.
