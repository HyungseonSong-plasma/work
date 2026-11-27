# FileRank: C
"""Explicit ordered GitHub workflow routes."""

from libs.frame import Registry, validate_unique


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
        if (not isinstance(workflow, str) or
                not workflow.endswith((".yml", ".yaml")) or
                "/" in workflow or "\\" in workflow or
                not workflow.rsplit(".", 1)[0].replace("_", "").replace("-", "").isalnum()):
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
