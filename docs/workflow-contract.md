# FileRank: C

# Reusable Workflow Contract — Test v1 (development)

Provider: `HyungseonSong-plasma/work`. The reusable test workflow builds the exact reviewed provider commit `c21f73ae8f1bd1f8d80f1ae3955c57607cf85896` (D5 integrated; Python package version `0.1.0.dev0`), pins checkout/setup-python actions and verifies the pinned setuptools backend wheel SHA256 before building. The workflow revision and embedded provider revision are intentionally distinct and reviewed together. No public release or license grant is implied.

A consumer owns its local event subscription, the fixed `tests/work_contract.py` script and least-privilege caller permissions. The script uses installed `work.libs` APIs, with no need to copy the provider source, YAML job mechanics or TOML registries. It must be self-contained (isolated Python, no caller cwd import), exit nonzero on failure, and not mutate remote resources. See `tests/work_contract.py` for a real two-test fixture.

Example caller (replace FULL_REVIEWED_WORKFLOW_SHA with the exact approved provider workflow commit):

```yaml
name: Work contract
on:
  workflow_dispatch:
permissions: {}
jobs:
  contract:
    permissions:
      contents: read
    uses: HyungseonSong-plasma/work/.github/workflows/reusable_test.yml@FULL_REVIEWED_WORKFLOW_SHA
```

Test v1 supports a fresh owner-initiated push or workflow_dispatch on a personal repository branch. Callers should restrict their normal event triggers to their own trusted refs; pull_request/pull_request_target, tags, reruns and untrusted authors are not accepted. A rejected event fails the validation step, rather than silently skipping the job. The provider checks out the caller event SHA and its own pinned commit in separate directories, verifies them, builds the wheel with an exact backend hash, and installs into a fresh environment outside the checkouts. The caller script must be a regular file at the exact fixed path with no symlink redirection. No secrets inheritance, runtime token, arbitrary path, ref, command, configuration override or mutation inputs are provided. The callee grants contents:read only; it cannot elevate caller permission. The isolated Python and reduced environment limit accidental imports/credentials; this is **not a sandbox** and the caller code must be trusted. It is not a release signature or byte-reproducibility guarantee.

The workflow logs caller repository/SHA, provider SHA, built wheel SHA256, installed package path and test outcome. It does not establish that the consumer has adequate tests or that write operations are authorized. All four existing mutation workflows remain local and unchanged. Before sharing those workflows, review repository-local policy ownership, authorization evidence, workflow identity, dispatch and serial/concurrency semantics. Never silently apply the provider's deletion policy to a consumer repository.

External adoption requires the consuming repository's own Work/authority gates. In particular work-controller classifies both .github and tests as B-rank; an exact scoped owner approval is required before changing those files. Do not bypass this by using a temporary branch.
