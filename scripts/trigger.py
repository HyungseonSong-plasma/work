# FileRank: C
"""Route an authorized PR comment to one execution workflow; never execute it."""

import json
import os
import sys
from urllib.error import HTTPError, URLError
from github.model import dispatch_workflow

from execute import comment_request, resolve_execution


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


def main():
    try:
        if (os.environ["GITHUB_EVENT_NAME"] != "issue_comment" or
                os.environ["GITHUB_RUN_ATTEMPT"] != "1"):
            raise ValueError("Only a new comment event can dispatch a workflow.")
        with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as stream:
            event = json.load(stream)
        repository = os.environ["GITHUB_REPOSITORY"]
        workflow, payload = route(event, repository, os.environ["GITHUB_REF"])
        dispatch_workflow(repository, workflow, payload)
        print(f"Submitted {workflow}: {payload['inputs']['request_id']}")
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as stream:
                stream.write(f"Submitted `{workflow}` for "
                             f"`{payload['inputs']['request_id']}`.\n\n"
                             "Execution result is reported by the dispatched run.\n")
        return 0
    except HTTPError as error:
        print(f"Dispatch failed: HTTP {error.code}", file=sys.stderr)
    except (URLError, ValueError, KeyError, TypeError, OSError) as error:
        print(f"Dispatch not confirmed: {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
