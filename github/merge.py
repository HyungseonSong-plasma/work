# FileRank: C
"""Merge a single, explicitly selected GitHub pull request."""

from dataclasses import dataclass

from work.libs.github import (JsonMutation, guarded_json_mutation, validate_pr_number,
                         validate_sha, review_repository, matches_pr_head)


@dataclass(frozen=True)
class MergeOperation:
    api: object
    repository: str
    ref: str
    pr_number: object
    expected_head_sha: str

    def prepare(self):
        number = validate_pr_number(self.pr_number)
        sha = validate_sha(self.expected_head_sha)
        root, repo = review_repository(self.api, self.repository, self.ref)
        default = repo["default_branch"]
        endpoint = f"{root}/pulls/{number}"
        pr = self.api("GET", endpoint)
        if not (
            pr["state"] == "open"
            and pr["draft"] is False
            and pr["merged"] is False
            and matches_pr_head(pr, self.repository, default, sha)
        ):
            raise ValueError(
                "PR must be open, non-draft, unmerged, target the default branch "
                "and match the expected head SHA."
            )
        # GitHub checks the expected SHA again during the merge operation.
        return JsonMutation(self.api, "PUT", f"{endpoint}/merge",
                            {"sha": sha, "merge_method": "merge"})

    @staticmethod
    def confirm(result):
        sha = result.get("sha")
        if result.get("merged") is not True:
            raise ValueError("GitHub did not confirm a successful merge.")
        return validate_sha(sha)


MERGE = guarded_json_mutation(MergeOperation.prepare, MergeOperation.confirm)
