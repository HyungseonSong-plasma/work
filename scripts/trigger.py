# FileRank: C
"""Route an authorized PR comment to one execution workflow; never execute it."""

from github.model import dispatch_workflow

from scripts.execute import comment_request, resolve_execution


def route(event, repository, ref):
    if event["repository"]["full_name"] != repository:
        raise ValueError("Request repository mismatch.")
    default = event["repository"]["default_branch"]
    if ref != f"refs/heads/{default}":
        raise ValueError("Trigger must run on the default branch.")
    execution, parameters = comment_request(event)
    scripts = resolve_execution(execution, parameters)
    if len(scripts) == 1:
        workflow = "single_run.yml"
    elif [script.name for script in scripts] == ["pr_merge.py", "branch_delete.py"]:
        workflow = "serial_run.yml"
    else:
        raise ValueError("Unsupported serial workflow.")
    comment_id = event["comment"]["id"]
    if type(comment_id) is not int or comment_id <= 0:
        raise ValueError("Invalid comment ID.")
    return workflow, {
        "ref": default,
        "inputs": {
            "execution": " - ".join(script.name for script in scripts),
            "parameters": parameters,
            "request_id": f"comment-{comment_id}",
        },
    }


def dispatch_request(event, repository, ref, dispatch=dispatch_workflow):
    """Validate and submit exactly one matching workflow."""
    workflow, payload = route(event, repository, ref)
    dispatch(repository, workflow, payload)
    return workflow, payload["inputs"]["request_id"]
