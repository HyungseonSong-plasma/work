# FileRank: C
"""Merge a single, explicitly selected GitHub pull request."""

from dataclasses import dataclass, field

from libs.github import (GUARDED_MUTATION, validate_pr_number, validate_sha,
                         review_repository, matches_pr_head)


@dataclass
class MergeOperation:
    """Fresh per-invocation state and operation-specific stage callbacks."""

    api: object
    repository: str
    ref: str
    pr_number: object
    expected_head_sha: str
    _endpoint: str = field(init=False, repr=False, compare=False)
    _default_branch: str = field(init=False, repr=False, compare=False)
    _pr: dict = field(init=False, repr=False, compare=False)

    def prepare(self):
        self.pr_number = validate_pr_number(self.pr_number)
        validate_sha(self.expected_head_sha)
        return self

    def review(self):
        root, repo = review_repository(self.api, self.repository, self.ref)
        self._default_branch = repo["default_branch"]
        self._endpoint = f"{root}/pulls/{self.pr_number}"
        self._pr = self.api("GET", self._endpoint)
        return self

    def validate(self):
        pr = self._pr
        if not (
            pr["state"] == "open"
            and pr["draft"] is False
            and pr["merged"] is False
            and matches_pr_head(pr, self.repository, self._default_branch, self.expected_head_sha)
        ):
            raise ValueError(
                "PR must be open, non-draft, unmerged, target the default branch "
                "and match the expected head SHA."
            )
        return self

    def mutate(self):
        # GitHub checks the expected SHA again during the merge operation.
        return self.api("PUT", f"{self._endpoint}/merge",
                        {"sha": self.expected_head_sha, "merge_method": "merge"})

    @staticmethod
    def confirm(result):
        sha = result.get("sha")
        if result.get("merged") is not True:
            raise ValueError("GitHub did not confirm a successful merge.")
        return validate_sha(sha)


MERGE = GUARDED_MUTATION.bind(
    prepare=MergeOperation.prepare,
    review=MergeOperation.review,
    validate=MergeOperation.validate,
    mutate=MergeOperation.mutate,
    confirm=MergeOperation.confirm,
)
