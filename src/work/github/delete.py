# FileRank: C
"""Target-specific GitHub deletions with explicit registration and validation."""

from urllib.parse import quote

from work.config import require_deletion
from work.github.actions import delete_actions_batch, delete_actions_run
from work.libs.github import review_repository, matches_pr_head
from work.libs.github import git_session


def _used_by_open_pr(api, root, repository, branch):
    """Check all open PR pages unless a matching reference already blocks deletion."""
    page = 1
    while True:
        pulls = api("GET", f"{root}/pulls?state=open&per_page=100&page={page}")
        if not isinstance(pulls, list):
            raise ValueError("Invalid open PR response.")
        for other in pulls:
            for side in ("head", "base"):
                endpoint = other[side]
                if endpoint["ref"] == branch and (
                    endpoint["repo"] is None
                    or endpoint["repo"]["full_name"] == repository
                ):
                    return True
        if len(pulls) < 100:
            return False
        page += 1


def delete_branch(api, git, repository, run_ref, number, sha, remote):
    """Derive the deletion target from GitHub, not from user-supplied refs."""
    require_deletion("branch")
    root, repo = review_repository(api, repository, run_ref)
    default = repo["default_branch"]

    pr = api("GET", f"{root}/pulls/{number}")
    if not (
        pr["state"] == "closed"
        and pr["merged"] is True
        and matches_pr_head(pr, repository, default, sha)
    ):
        raise ValueError("Expected a merged PR into the default branch with matching head SHA.")
    head = pr["head"]
    if not head["repo"] or head["repo"]["full_name"] != repository:
        return "Skip: fork or missing head repository."

    branch = head["ref"]
    if branch in {default, "main", "master"}:
        return "Skip: default or reserved branch."
    ref = f"refs/heads/{branch}"
    git("check-ref-format", ref)
    current = git("ls-remote", "--exit-code", "--refs", remote, ref, allowed=(0, 2))
    if current.returncode == 2:
        return "Skip: branch already absent."
    if current.stdout.rstrip("\n") != f"{sha}\t{ref}":
        return "Skip: branch head has changed."

    details = api("GET", f"{root}/branches/{quote(branch, safe='')}")
    if details["protected"] is not False or details["commit"]["sha"] != sha:
        return "Skip: protected branch or changed head."

    if _used_by_open_pr(api, root, repository, branch):
        return "Skip: branch is used by an open PR."

    # The server rejects the ref update if its SHA changed since verification.
    git("push", f"--force-with-lease={ref}:{sha}", remote, f":{ref}")
    return f"Deleted merged PR head: {branch}"


def delete_branch_with_git(api, repository, run_ref, number, sha, remote):
    """Run branch deletion inside the shared isolated Git session."""
    with git_session() as git:
        return delete_branch(api, git, repository, run_ref, number, sha, remote)


DELETIONS = {
    "branch": delete_branch_with_git,
    "actions": delete_actions_run,
    "actions_batch": delete_actions_batch,
}


def delete(target, **parameters):
    """Dispatch to one explicit deletion implementation, never discover code."""
    if target not in DELETIONS:
        raise ValueError("Unregistered deletion target.")
    require_deletion("actions" if target == "actions_batch" else target)
    return DELETIONS[target](**parameters)
