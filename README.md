<!-- FileRank: C -->
# work
work laboratory

The reusable library is now under the canonical `work.libs` import namespace. The source checkout continues to run `python3 -m app` from the repository root; no top-level `libs` compatibility package is provided.

## Framework distribution (development)

D3 builds the reusable `work-framework` distribution (`0.1.0.dev0`, Python 3.11+). Its wheel and sdist contain the explicitly listed `work` and `work.libs` packages, including both private implementation modules; they do not install the repository application, domain package, TOML policies, tests or YAML workflows. There are no third-party Python runtime dependencies. Real Git transport additionally needs Git and authenticated GitHub CLI where used. No public release or license grant is implied.

From a trusted, reviewed source checkout, build in an independent environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install build==1.3.0
python -m build
python tests/verification/packaging_probe.py --dist dist
```

The PEP 517 backend is pinned in `pyproject.toml`; build isolation may fetch that backend. Use a trusted package index or a reviewed offline wheelhouse (PIP_NO_INDEX and PIP_FIND_LINKS). Verify artifact hashes against the reviewed build evidence, then install the wheel into a consumer virtual environment outside this checkout:

```sh
python -m pip install --no-deps /absolute/path/work_framework-0.1.0.dev0-py3-none-any.whl
python -c 'from work.libs.frame import FrameContract; print(FrameContract(("action",)).bind(action=lambda x: x + 1).execute(1))'
```

The smoke probe builds (unless artifacts are supplied), checks archive contents and source bytes, and installs the wheel and sdist independently in clean environments outside the repository. Source checkouts can shadow an installed package; verify the installed module path outside the checkout. The physical `src/work` move is deferred until the application bootstrap and trusted workflow execution paths can be migrated together in D4. No path injection or compatibility alias is added. Existing `python3 -m app` and operation workflows still use the trusted source checkout. The installed framework has no CLI entrypoint or project policy resources. Distribution naming, licensing and the stable release contract remain subject to review.

## Execution

Use [Single Run](../../actions/workflows/single_run.yml) for one execution identifier or [Serial Run](../../actions/workflows/serial_run.yml) for a dependent chain. Both run on the default branch.

| execution | Operation |
| --- | --- |
| `pr_merge.py` | Merge one pull request |
| `branch_delete.py` | Delete the unchanged head of a merged pull request |
| `pr_merge.py - branch_delete.py` | Merge, then delete in the same run |

Supply shared parameters as a JSON object containing `pr_number` and `expected_head_sha` (the full reviewed PR head commit SHA).

The dispatcher validates the full registered execution list before starting. Single Run has one job (Merge or Delete). Serial Run has two jobs (Merge then Delete); Delete starts only after Merge succeeds. The current serial workflow supports exactly the two registered execution identifiers in that order. Branch deletion still applies its own safety checks and may skip deletion. If deletion fails after a successful merge, retry only `branch_delete.py` with the same parameters in Single Run.

Only the explicitly requested operations run; ordinary PR merges do not automatically trigger branch deletion.

**PR worker authorization (policy A, #66):** Single Run and Serial Run trust GitHub's repository dispatch authorization (normally repository write access for manual dispatch). Direct dispatch by a permitted writer is intentionally supported; workers do not independently require the owner or re-fetch an approval comment. The optional request ID is a correlation label, not an authorization credential. Default-branch, first-attempt, exact execution chain, PR state, SHA and branch lease safeguards still apply. Chat/scheduled Trigger requests remain owner-only. Actions Run deletion has its separate, stricter owner/source approval policy below. Repository access controls, branch protection and rulesets are distinct from these application checks; users who can modify trusted workflow code are outside this application's trust boundary.

### Chat and scheduled execution

An owner-authored top-level comment on the target PR can request execution without opening the Actions UI. Only Trigger subscribes to PR comments. It validates the owner and the full registered execution list, then submits exactly one workflow_dispatch request to Single Run or Serial Run. The execution workflows no longer subscribe to comments. Trigger reports submission, not execution success; the target run has the source comment ID in its run name. The target workflow independently validates the full chain and expected execution count:

```text
/execute {"execution":"pr_merge.py - branch_delete.py","expected_head_sha":"<full reviewed PR head SHA>"}
```

Replace the placeholder with the real SHA. The PR number is derived from the comment's PR. Only newly created comments from the repository owner are accepted; edits, other authors and comment-run replays are rejected. Trigger and the execution workflows check out their trusted default-branch event commits, not the PR's code. Trigger has contents: read and actions: write; only the execution jobs have contents: write. A fresh request is required instead of rerunning a previous run.

For scheduled submission, an explicitly owner-authored comment can use the same JSON with the prefix `/queue `. The ChatGPT scheduled task may submit an equivalent `/execute ` comment with a `queue_comment_id` identifying the approval. A queue entry is not itself an execution trigger. The scheduler must verify the author's ID and current PR state/SHA and avoid resubmitting a queue ID already dispatched. Never infer approval from ordinary PR text. Do not automatically retry failed commands; submit a fresh explicit request.

### Inspecting execution results

Open [Trigger](../../actions/workflows/trigger.yml) to inspect request submission, then find the corresponding Single Run or Serial Run by its `comment-<id>` run-name suffix. In Serial Run, inspect Merge and Delete separately. A successful Delete job can also represent a safety skip; verify its log and branch state before reporting that the branch was removed.

### GitHub integration

The canonical `work/libs/github.py` module provides shared GitHub validation contracts, REST and isolated Git transport, and an ordered `WorkflowRegistry`. It depends on the standard library, `work/libs/frame.py` and private `work/libs/_github_transport.py`; GitHub operations remain in `github/`. The private transport module owns `GitHubClient`, its default `CLIENT` binding and `git_session`; `work.libs.github` re-exports the same objects. Application and domain consumers continue importing only from `work.libs.github`. `GitHubClient` consolidates the REST request/response scope; its JSON, dispatch and delete methods retain their distinct response confirmation rules. The default client reads token and API URL on each request, not on import. `app/commands/trigger.py` eagerly composes the trusted route registry from `config/workflows.toml` and the application execution resolver. `github/trigger.py` receives these explicitly, validates GitHub PR comments, and dispatches exactly one matching workflow. GitHub domain modules do not import the application layer. The root `app/` package provides the only command-line entry point; `github/` contains GitHub operations; `app/commands/execute.py` runs isolated command subprocesses. Legacy `.py` execution identifiers are protocol strings only; no scripts directory or marker files are required. Workflows use `python3 -m app` from the trusted repository root, so no PYTHONPATH override is necessary.

### Unified CLI

```sh
python3 -m app --help
python3 -m app trigger
python3 -m app execute --single
python3 -m app execute --serial-stage 1
python3 -m app execute --serial-stage 2
python3 -m app test
```

These commands consume the existing GitHub event and execution environment variables. The dispatcher launches registered commands as isolated `python3 -m app merge` or `python3 -m app delete branch` subprocesses, with a fixed allowlist and fail-fast exit handling. `work/libs/command.py` provides the common command binding, regulated execution and registry mechanics; `work/libs/workflow.py` provides event validation, PR context and result reporting; `app/wiring.py` projects its single registry instance onto the exact execution allowlist and resolves execution identifier chains without filesystem discovery. The former `task.py` and `TASKS` registry are removed. For workflow execution use `execute`, which validates the whole chain before starting. Serial stage ordering remains enforced by GitHub Actions `needs`; invoking stage 2 manually does not establish stage 1 success. The existing branch deletion policy still requires an already merged PR.

### Adding CLI commands

`work/libs/command.py` owns generic parser binding and dispatch through `run_cli`; `app/cli.py` supplies configured commands, the program name and GitHub-specific execution error reporting. Parser/configuration errors remain outside the execution error handler. To add a command, define a subclass of `Command` from `work/libs/command.py` in `app/commands/` with a help string, optional `configure(parser)`, and a declarative `plan` (or explicit `targets` plans), decorate it with `@register("command-name")`, explicitly import the module in `app/commands/__init__.py`, and add its name to `config/commands.toml`. Duplicate registrations and invalid command interfaces are rejected. No filesystem discovery or user-controlled module imports are used. Only commands with an explicit `workflow_execution` tuple can be selected by the restricted workflow allowlist. Unknown, duplicate or missing execution bindings fail closed. CLI registration alone grants no workflow eligibility.

Run offline regression tests with `python3 -m app test`.

For an end-to-end CLI regression check, use a reviewed documentation-only PR and submit the existing serial execution command. Confirm that Trigger submits exactly one Serial Run, Merge completes before Delete starts, the PR is merged, and its unchanged head branch is absent. Inspect the run logs rather than relying only on the workflow conclusion.

### Adding workflow routes

Register exact ordered execution identifier arrays and workflow filenames in `config/workflows.toml`. The loader checks each execution identifier against `config/executions.toml`. `route()` uses the same registry lookup for all chains. Unknown and duplicate routes are rejected. Registration does not create a workflow or grant permission to run new execution identifiers: the corresponding YAML, worker validation, task allowlist and execution contract must also support the route. CLI command registration remains separate.

When verifying a workflow route change, confirm the Trigger and worker runs both use the post-change default-branch commit. A successful merge of the change itself exercises the previous implementation and is not sufficient evidence for the new route registry.

### Registry configuration

The C-rank TOML registries under `config/` define CLI command names, execution allowlists, ordered workflow routes, deletion availability and test suites. Python 3.11 or newer is required for the standard-library `tomllib` parser. Code still binds explicitly imported implementations; TOML cannot import arbitrary modules, create workflow permissions or bypass validation. `config/deletions.toml` enables branch and Actions Run deletion; issue deletion remains disabled because the default GITHUB_TOKEN returned FORBIDDEN in the disposable issue #15 probe. The permission strings are documentation, not authorization. The existing execution YAML and comment protocol remain unchanged. The `/execute` and `/queue` request protocol and GitHub API payloads remain JSON.

For TOML registry regression verification, confirm that the worker and Trigger use the same reviewed configuration commit and that the serial route is selected from `config/workflows.toml`.

### Test registry

The offline test suite uses `config/tests.toml` as its ordered manifest. Each ordinary `tests/suites/` module registers a subclass of `TestSuite` from `work/libs/testing.py` with `@register(name)` from `tests/wiring.py`; `tests/suites/__init__.py` imports implementations and the registered `tests/suites/registry_contract.py` self-test explicitly. The registered CLI command `app/commands/test.py` lazily imports the suites and builds the configured suite. `work/libs/testing.py` owns runtime runners, loaded-suite validation and independent SuiteRegistry; private `work/libs/_test_grammar.py` owns the declarative static AST grammar and has no project dependencies. `work.libs.testing` re-exports the existing grammar bindings without wrappers. Static declaration shape and runtime callback/value validation remain distinct; `tests/wiring.py` owns manifest selection and the exact self-test identity. `tests/fixtures.py` owns deterministic project fixtures. Each TestSuite creates a fresh context via context_type in setUp (a generic mutable namespace by default; project suites explicitly select their fixture). The test runners reuse shared registry and validation primitives without forcing scoped unittest semantics into the linear Frame runner. WorkflowTestContext supplies independent event and isolated environment fixtures, ActionsTestContext supplies mock deletion transport and approval fixtures, and ConfigurationTestContext scopes temporary configuration roots. Related scenarios use named case tables with TestSuite.run_cases(rows, check), which rejects empty/duplicate case names, creates a fresh context per row and reports each row via unittest.subTest. Test method counts reflect groups, not individual rows; the individual contracts and expected outcomes remain visible in each suite. Distinct test procedures remain separate methods. Positive and negative rows run with independent contexts. The pilot adds TestSuite.run_contract(act, check, *, arrange=None, raises=None) for a single action and TestSuite.run_scenario(steps, check, *, arrange=None) for ordered named steps sharing one fresh context. Optional arrange(ctx) returns a non-suppressing context manager spanning action/steps and check, with cleanup on failure. Contract expected exceptions apply only to the action and are passed to check; scenario steps stop on unexpected failure and report the failing step. Ordinary tests must declare exactly one final runner entrypoint: run_cases(cases, check), run_contract(act, check, ...) or compact run_contract(check=check), or run_scenario(steps, check, ...). Compact contracts retain a cohesive operation and checks in one callback. The registry enforces AST declaration shape and runner lifecycle before loading tests, while the runners validate callbacks and names at runtime. Only the exact registered framework self-test class is exempt. This is a structural policy, not a security sandbox or a proof of assertion adequacy. Concrete test methods retain their assertions and explicit expected values; test contexts do not derive expectations from production validators or registries. unittest discovery and explicit suite registration remain unchanged. Missing, unknown, duplicate or empty suites are rejected instead of silently reducing coverage. Keep fixtures and assertions independent of production registry data. Run the full suite with the `python3 -m app test` command. To extend tests, add a registered suite and its manifest entry; no dispatcher conditionals or dynamic imports are required.

Verify the TOML serial route with a documentation-only PR on the post-migration default branch; confirm both job conclusions and actual branch removal.

The command framework owns the prepare -> validate -> action -> report -> exit lifecycle through one fixed `FrameContract`/`Frame` in `work/libs/command.py`; the library adapts per-invocation args, validated context, result and optional reporting without requiring concrete commands to define another runner. `CommandRegistry` instances are independent of application/configuration imports; `app/wiring.py` owns the manifest and workflow projection. CommandPlan declares callbacks and explicit result/status semantics; `local_plan` lives in the library, while `work/libs/workflow.py` composes workflow_plan and pr_plan with the existing CommandPlan lifecycle through context_plan, also used by app/wiring.py for Actions approval. Optional preflight runs before context construction; context-specific validation remains independent. `app/wiring.py` injects the project execution resolver into pr_plan and connects actions_plan to the dedicated `github/actions.py` approval context. The library never imports application, test, GitHub domain or configuration packages. No `app/framework/` package remains. Concrete modules define only configuration, operation-specific validation/action/report callbacks and registration metadata. Command.bind and Command.execute are framework-owned and cannot be overridden by registered implementations; reserved parser dispatch fields are rejected. The CLI dispatches through the selected registered class, never through a parser-supplied handler. Context snapshots environment values per invocation. PRContext validates registered PR inputs using an explicitly supplied resolver; ActionsContext in `github/actions.py` independently validates the dedicated worker and unchanged owner approval before normalizing single and batch inputs. GitHub handlers retain remote state checks. The offline test command does not require a GitHub context. Registration is a structural contract for trusted Python implementations, not a security sandbox.

### GitHub deletion framework

`github/delete.py` exposes `delete(target, **parameters)` backed by explicitly registered branch and Actions handlers. The legacy `branch_delete.py` identifier maps directly to the registered `delete branch` command; branch deletion and target bindings live in `github/delete.py`; Actions wire/request, policy, worker approval and batch orchestration live in `github/actions.py`; the private `github/_actions_retention.py` domain module owns retention guards, evidence retrieval and deterministic successful-listing validation. The evidence validator performs no I/O or mutation, and the batch handler independently invokes retention at preflight and fresh review. Shared PR parameter parsing and HTTP 204 deletion transport live in the GitHub framework.

Actions Run deletion is available through an owner-authored PR comment or manual dispatch of [Delete Actions Run](../../actions/workflows/actions_delete.yml), with the exact reviewed run ID, full head SHA and run attempt. The workflow runs on the default branch, first attempt only. Manual dispatch requires the owner; a Trigger dispatch must cite the exact unchanged owner PR comment, which the worker re-fetches and validates against the inputs. The workflow has `actions: write` and `contents: read`, not `contents: write`; existing merge/delete workers retain their original permissions. Only completed runs in this repository may be deleted. The current run, pinned evidence IDs, and the newest successful run(s) for each listed audit workflow are retained according to config/actions_policy.toml. Explicit batches are limited to 30 reviewed targets. No automatic age-based cleanup is implemented. Each batch preflights all targets, then revalidates and deletes sequentially; later errors stop the batch but cannot restore earlier deletions. For protected workflows the successful-run listing must contain exactly min(total_count, 100) rows, in descending creation-time/run-ID order with valid GitHub UTC second-resolution timestamps. A successful target must agree with its listed rank and reviewed SHA/attempt, or be strictly older than the last row of a full first page of a longer listing; a missing target in a complete listing or within the first-page range is rejected. Contradictory success evidence is rejected. These checks apply at batch preflight and fresh review; a changed but independently consistent listing may be accepted. Metadata is rechecked immediately before DELETE, but the GitHub endpoint does not offer an atomic attempt guard; do not rerun a target concurrently. The controller remains submission-only for the original PR execution chains; it cannot submit Actions deletion. The separate owner PR comment route is `/execute {"execution":"delete actions","run_id":123,"expected_head_sha":"<full run head SHA>","expected_run_attempt":1}`. No queue_comment_id is accepted. The isolated deletion workflow also receives issues: read and pull-requests: read to verify the source comment and PR; existing workers are unchanged.

After changing the shared deletion framework, verify the legacy branch execution identifier still dispatches to the registered GitHub branch handler in a post-change serial run.

Batch comment: `/execute {"execution":"delete actions","runs":[{"run_id":123,"expected_head_sha":"<full SHA>","expected_run_attempt":1}]}`. The original single-run format remains supported. Never use implicit selectors. Only one deletion workflow may execute at a time; GitHub may replace pending concurrency-group runs, so submit one batch at a time.

The approved external execution IDs `pr_merge.py` and `branch_delete.py` remain unchanged, as do workflow YAML, permissions, comment syntax and the Controller queue allowlist. Branch and Actions deletion share DeleteCommand but keep independent authorization and target validation; only branch deletion is eligible for PR execution chains.

Post-refactor live verification uses the unchanged serial PR comment contract to launch the registered merge and delete branch commands via the unified registry.

After standardizing the thin command adapters, verify the unchanged serial comment route and the dedicated Actions deletion context through the post-change default branch.

Verify the context model on the post-change default branch using the unchanged serial comment route and both single and batch Actions deletion requests.

Shared SHA, PR number, default-ref and execution-comment parsing functions live in `work/libs/github.py`. Trigger and workers independently invoke these validators; repository/default-ref review and exact PR base/head comparison are shared primitives. Operation-specific eligibility, mutation guards, skip/reject behavior and result confirmation remain in the handlers. Dispatch submits once; merge and branch deletion retain exact SHA/lease guards; Actions batches preflight all targets and re-review each before deletion. The merge pilot uses the fixed JSON mutation contract (prepare -> mutate -> confirm) in `work/libs/github.py`, built on `FrameContract` and the composed, non-subclassable `Frame` runner in `work/libs/frame.py`. The runner validates all callback names and signatures before binding, executes in declared order, threads each result to the next stage, and propagates failures without retrying or invoking later stages. `github/merge.py` declares only preparation (input validation, fresh repository/PR review and eligibility checks) and result confirmation; the frozen input model holds no mutable review state. Preparation returns an explicit `JsonMutation` request with the exact SHA guard; the library owns the mutation callback. The JSON contract is not used for 204 deletion, Git lease, or batch mutation, and is a structural contract for trusted implementations, not a security boundary. Branch skip paths, Actions batch preflight/re-review, and Trigger dispatch retain their existing separate execution contracts; no single generic mutation policy is imposed. Deletion policy checks remain at both the public dispatcher and directly callable mutation handlers as independent safeguards.

Verify the script-free execution registry on the post-change default branch via the unchanged serial PR comment and dedicated Actions deletion route.

### Shared framework mechanics

`work/libs/frame.py` is a standard-library-only foundation for the application, test and GitHub frameworks. The GitHub framework is absorbed into `work/libs/github.py`; no `github/framework/` package remains. Its ordered `Registry`, explicit selection and uniqueness checks, callback signature validation and reserved-method checks share mechanisms, not domain policies. Each framework keeps its own key/schema constraints, exception contract, manifest completeness rules, execution lifecycle and authorization. `tests/suites/registry_contract.py` contains the exact-class-exempt framework self-tests, including direct tests of the shared library. No `framework_tests/`, `tests/framework/` or compatibility shim remains.

### Reproducible snapshot verification

For behavior-preserving changes, use the versioned [offline verification probes](tests/verification/README.md) to compare two explicitly trusted, clean, exact-SHA snapshots. This is separate from the ordinary test command and adds no automatic or mandatory CI.

### Architecture contract

The offline suite enforces project-owned architecture rules in `tests/architecture.py` through the existing configuration suite. Library imports follow an explicit DAG: frame, private _github_transport and private _test_grammar have no project dependency; command, github and testing may import frame; github may additionally import _github_transport; testing may additionally import _test_grammar; workflow may import command and github. Only work.libs.github may import the private transport module and only work.libs.testing may import the private grammar module in production. Libraries may not import app, github domain, tests or config. Domain code may use config, domain modules and the frame/github/workflow libraries, but not app or tests. Config stays independent; app may use domain and command/workflow/github/frame libraries, with only the direct lazy suite/wiring imports in the test command action permitted for tests. Old framework paths and undeclared library modules are rejected. The checker scans Python import statements (including nested and relative ones), rejects direct dynamic import/execution constructs in production, and runs fresh-process import probes and framework ownership assertions. New library modules or dependency edges require an explicit policy update. This is an offline structural regression check, not a sandbox or proof of arbitrary dynamic behavior; it is exercised by `python3 -m app test`, not a new mandatory GitHub status check.

Test contract and scenario runners share a single non-suppressing context scope, while keeping distinct callback/exception semantics. Fresh-process import probes share an independent fixture helper; each test declares its own expected forbidden modules. Registry decorators remain distinct because their key/value contracts differ; the common Registry.add already owns duplicate-before-validation behavior.

Trigger and Actions approval independently check unchanged comment timestamps using the same narrow GitHub predicate; owner, sender, workflow and source bindings remain separate. Execution resolution and subprocess entry independently require registered chain membership using the shared workflow helper; project order/cardinality, fresh route lookup and subprocess status rules remain local. Actions request and target validation share one ordered field declaration; wire comparison still precedes normalization and the mutation handler revalidates targets.
