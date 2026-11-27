# FileRank: C
"""GitHub framework: wire contracts, routing, mutation and transport bindings."""

from dataclasses import dataclass
import json
import re

from libs.frame import FrameContract, Registry, validate_unique
from libs._github_transport import CLIENT, GitHubClient, git_session


# Input and remote-state validation

def validate_sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("Expected a full lowercase Git commit SHA.")
    return value


def validate_pr_number(value):
    if type(value) is int:
        value = str(value)
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*", value):
        raise ValueError("Invalid pull request number.")
    return value


def require_default_ref(ref, default):
    if not isinstance(default, str) or not default or ref != f"refs/heads/{default}":
        raise ValueError("Run only on the current default branch.")


def is_unchanged_comment(comment):
    """Check the original comment timestamps; callers own approval policy."""
    return comment["created_at"] == comment["updated_at"]


def parse_execute_comment(body):
    prefix = "/execute "
    if not isinstance(body, str) or not body.startswith(prefix):
        raise ValueError("Not an execution command.")
    return json.loads(body[len(prefix):])


def parse_pr_parameters(raw):
    parameters = json.loads(raw)
    if not isinstance(parameters, dict) or set(parameters) != {
        "pr_number", "expected_head_sha"
    }:
        raise ValueError("Provide pr_number and expected_head_sha only.")
    return (validate_pr_number(parameters["pr_number"]),
            validate_sha(parameters["expected_head_sha"]))


def review_repository(api, repository, ref):
    """Read repository metadata and require its current default ref."""
    root = f"repos/{repository}"
    repo = api("GET", root)
    require_default_ref(ref, repo["default_branch"])
    return root, repo


def matches_pr_head(pr, repository, default, sha):
    """Compare the reviewed base repository/ref and exact head SHA."""
    return (pr["base"]["ref"] == default
            and pr["base"]["repo"]["full_name"] == repository
            and pr["head"]["sha"] == sha)


# Ordered workflow routing

class WorkflowRegistry:
    """Map exact, ordered execution chains to explicitly registered workflows."""

    def __init__(self):
        self._routes = Registry()

    @staticmethod
    def _key(execution):
        if isinstance(execution, (str, bytes)):
            raise ValueError("Execution must be a sequence of script names.")
        key = tuple(execution)
        if not key or any(not isinstance(name, str) or not name for name in key):
            raise ValueError("Expected a nonempty execution chain.")
        validate_unique(key, "Duplicate scripts in workflow route.")
        return key

    def register(self, execution, workflow):
        key = self._key(execution)
        self._routes.add(key, workflow, duplicate="Duplicate workflow route.",
                         validate=self._validate_workflow)

    @staticmethod
    def _validate_workflow(workflow):
        if (not isinstance(workflow, str) or not workflow.endswith((".yml", ".yaml"))
                or "/" in workflow or "\\" in workflow):
            raise ValueError("Expected a workflow filename.")
        stem = workflow.rsplit(".", 1)[0]
        if not stem.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Expected a workflow filename.")

    def resolve(self, execution):
        key = self._key(execution)
        return self._routes.resolve(key, unknown="Unregistered workflow route.")


    @classmethod
    def from_entries(cls, entries, allowed_executions):
        """Load validated route data, never importing or executing configuration values."""
        if not isinstance(entries, list) or not entries:
            raise ValueError("Invalid workflow registry.")
        registry = cls()
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"execution", "workflow"}:
                raise ValueError("Invalid workflow route entry.")
            if not isinstance(entry["execution"], list):
                raise ValueError("Workflow execution must be an array.")
            chain = cls._key(entry["execution"])
            if not set(chain).issubset(allowed_executions):
                raise ValueError("Workflow contains a disabled or unknown execution.")
            registry.register(chain, entry["workflow"])
        return registry


# A JSON mutation must be prepared before it can run and confirmed afterwards.
_GUARDED_JSON_MUTATION = FrameContract(("prepare", "mutate", "confirm"))


@dataclass(frozen=True)
class JsonMutation:
    api: object
    method: str
    endpoint: str
    payload: dict

    def execute(self):
        if type(self) is not JsonMutation or self.method not in ("POST", "PUT", "PATCH"):
            raise TypeError("Expected a prepared JSON mutation.")
        return self.api(self.method, self.endpoint, self.payload)


def guarded_json_mutation(prepare, confirm):
    """Bind domain checks around the fixed JSON mutation executor."""
    return _GUARDED_JSON_MUTATION.bind(prepare=prepare, mutate=JsonMutation.execute,
                                      confirm=confirm)
