# FileRank: C
"""Actions wire contract, worker approval and reviewed batch deletion."""

import json
import re

from config import require_deletion, load_registry
from github._actions_retention import check_retention as _check_retention
from work.libs.github import (CLIENT, validate_sha, review_repository,
                         require_default_ref, parse_execute_comment, validate_pr_number,
                         is_unchanged_comment)
from work.libs.workflow import Context


# Request and policy: one wire schema and fresh policy validation.

_TARGET_FIELDS = ("run_id", "expected_head_sha", "expected_run_attempt")


def actions_request(request):
    """Validate the single-run or exact batch request."""
    if not isinstance(request, dict) or request.get("execution") != "delete actions":
        raise ValueError("Invalid Actions deletion request.")
    if set(request) == {"execution", "runs"}:
        targets = validate_actions_targets(request["runs"])
        return {"runs": json.dumps(targets, sort_keys=True, separators=(",", ":"))}
    if set(request) != {"execution", *_TARGET_FIELDS}:
        raise ValueError("Invalid Actions deletion request.")
    target = {key: request[key] for key in _TARGET_FIELDS}
    validate_actions_targets([target])
    return {key: str(value) for key, value in target.items()}


def _positive_int(value):
    return type(value) is int and value > 0


def _workflow_path(value):
    return isinstance(value, str) and re.fullmatch(
        r"\.github/workflows/[A-Za-z0-9_-]+\.ya?ml", value)


def _unique_items(values, valid_item, *, nonempty=False):
    return (isinstance(values, list) and (not nonempty or bool(values))
            and all(valid_item(value) for value in values)
            and len(values) == len(set(values)))


# Field order is error precedence. Shape is derived from the same declaration.
_POLICY_RULES = (
    ("max_batch", lambda value: type(value) is int and 1 <= value <= 50,
     "Invalid batch limit."),
    ("keep_successful", lambda value: type(value) is int and 1 <= value <= 20,
     "Invalid retention count."),
    ("protected_workflows", lambda values: _unique_items(values, _workflow_path, nonempty=True),
     "Invalid retained workflow paths."),
    ("pinned_run_ids", lambda values: _unique_items(values, _positive_int),
     "Invalid pinned run IDs."),
)


def actions_policy():
    policy = load_registry("actions_policy")
    if not isinstance(policy, dict) or set(policy) != {key for key, _, _ in _POLICY_RULES}:
        raise ValueError("Invalid Actions policy.")
    for key, valid, message in _POLICY_RULES:
        if not valid(policy[key]):
            raise ValueError(message)
    return policy


def validate_actions_targets(targets, policy=None):
    policy = actions_policy() if policy is None else policy
    if not isinstance(targets, list) or not 1 <= len(targets) <= policy["max_batch"]:
        raise ValueError("Invalid Actions batch size.")
    ids = set()
    for target in targets:
        if not isinstance(target, dict) or set(target) != set(_TARGET_FIELDS):
            raise ValueError("Invalid Actions target.")
        if not all(_positive_int(target[key]) for key in ("run_id", "expected_run_attempt")):
            raise ValueError("Expected positive integer run ID and attempt.")
        validate_sha(target["expected_head_sha"])
        if target["run_id"] in ids:
            raise ValueError("Duplicate Actions run ID.")
        ids.add(target["run_id"])
    return targets


# Worker approval: compare wire inputs before normalizing targets.

def _request_from_args(args):
    """Build the exact single or batch request before checking approval."""
    if args.runs:
        if any(value is not None for value in
               tuple(getattr(args, key) for key in _TARGET_FIELDS)):
            raise ValueError("Choose single or batch, not both.")
        return {"execution": "delete actions", "runs": json.loads(args.runs)}
    return dict(execution="delete actions",
                **{key: getattr(args, key) for key in _TARGET_FIELDS})


def _approved_targets(inputs, batch):
    """Normalize only after approval has been checked against the wire inputs."""
    if batch:
        return json.loads(inputs["runs"])
    return [{"run_id": int(inputs["run_id"]),
             "expected_head_sha": inputs["expected_head_sha"],
             "expected_run_attempt": int(inputs["expected_run_attempt"])}]


class ActionsContext(Context):
    """Validate exact owner approval, then normalize single and batch targets."""

    def __init__(self, args, env=None, api=CLIENT.request):
        super().__init__(env)
        self.args = args
        self.api = api

    def validate(self):
        self.require_event("workflow_dispatch", fresh=True)
        args = self.args
        # Preserve the approved wire format during comparison, normalize afterwards.
        inputs = actions_request(_request_from_args(args))
        self._validate_approval(self.read_event(), inputs)
        if self.run_id <= 0:
            raise ValueError("Invalid current run ID.")
        self.targets = _approved_targets(inputs, args.runs)
        return self

    def _validate_approval(self, event, inputs):
        repository, ref = self.repository, self.ref
        actor_id, workflow_ref = self.actor_id, self.workflow_ref
        request_id, source_pr = self.args.request_id, self.args.source_pr
        api = self.api
        repo = event["repository"]
        owner = str(repo["owner"]["id"])
        if not (
            repo["full_name"] == repository
            and workflow_ref == f"{repository}/.github/workflows/actions_delete.yml@{ref}"
        ):
            raise ValueError("Unauthorized Actions deletion workflow.")
        require_default_ref(ref, repo["default_branch"])
        sender = event["sender"]
        if str(sender["id"]) != actor_id:
            raise ValueError("Workflow actor mismatch.")
        if not request_id and not source_pr:
            if actor_id != owner:
                raise ValueError("Manual deletion requires the owner.")
            return
        if not re.fullmatch(r"comment-[1-9][0-9]*", request_id) or not isinstance(source_pr, str):
            raise ValueError("Invalid source comment or PR.")
        validate_pr_number(source_pr)
        if actor_id != owner and not (
            actor_id == "41898282" and sender["login"] == "github-actions[bot]"
        ):
            raise ValueError("Unauthorized dispatch actor.")
        self._validate_source(api, repository, repo, request_id, source_pr, inputs)

    def _validate_source(self, api, repository, repo, request_id, source_pr, inputs):
        """Re-fetch the exact source PR/comment and compare approved wire inputs."""
        root = f"repos/{repository}"
        comment_id = int(request_id.split("-", 1)[1])
        comment = api("GET", f"{root}/issues/comments/{comment_id}")
        pr = api("GET", f"{root}/pulls/{source_pr}")
        api_url = self.env.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
        if not (
            comment["id"] == comment_id
            and comment["user"]["id"] == repo["owner"]["id"]
            and comment["author_association"] == "OWNER"
            and is_unchanged_comment(comment)
            and comment["issue_url"] == f"{api_url}/{root}/issues/{source_pr}"
            and pr["number"] == int(source_pr)
            and pr["base"]["repo"]["full_name"] == repository
        ):
            raise ValueError("Source comment is not an unchanged owner PR request.")
        request = parse_execute_comment(comment["body"])
        if actions_request(request) != inputs:
            raise ValueError("Source approval does not match dispatch inputs.")


# Mutation: preflight the batch, then freshly review each target.

def _review_run(api, root, repo, repository, target, policy):
    endpoint = f"{root}/actions/runs/{target['run_id']}"
    run = api("GET", endpoint)
    if not (
        run["id"] == target["run_id"]
        and run["repository"]["id"] == repo["id"]
        and run["repository"]["full_name"] == repository
        and run["status"] == "completed"
        and run["head_sha"] == target["expected_head_sha"]
        and run["run_attempt"] == target["expected_run_attempt"]
    ):
        raise ValueError("Expected the reviewed completed run in this repository.")
    _check_retention(api, root, repository, repo["id"], run, policy)
    return endpoint, run


def delete_actions_batch(api, remove, repository, run_ref, targets, current_run_id,
                         report=print):
    """Validate every target before the first DELETE, then revalidate each."""
    require_deletion("actions")
    policy = actions_policy()
    validate_actions_targets(targets, policy)
    if type(current_run_id) is not int or current_run_id <= 0:
        raise ValueError("Invalid current run ID.")
    if any(target["run_id"] == current_run_id for target in targets):
        raise ValueError("Cannot delete the current workflow run.")
    root, repo = review_repository(api, repository, run_ref)
    reviewed = [_review_run(api, root, repo, repository, target, policy)
                for target in targets]
    results = []
    for target, (endpoint, run) in zip(targets, reviewed):
        fresh_endpoint, fresh = _review_run(api, root, repo, repository, target, policy)
        if fresh_endpoint != endpoint or fresh != run:
            raise ValueError("Run metadata changed before deletion.")
        remove(endpoint)
        result = f"Deleted Actions run: {target['run_id']}"
        results.append(result)
        report(result)
    return results


def delete_actions_run(api, remove, repository, run_ref, run_id,
                       expected_head_sha, expected_run_attempt, current_run_id):
    return delete_actions_batch(
        api, remove, repository, run_ref,
        [{"run_id": run_id, "expected_head_sha": expected_head_sha,
          "expected_run_attempt": expected_run_attempt}], current_run_id,
        report=lambda message: None)[0]
