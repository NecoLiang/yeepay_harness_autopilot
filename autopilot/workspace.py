"""Per-ticket git worktrees, and publishing them to GitHub as the agent account.

Claude edits and commits inside the worktree but cannot push; only this module talks to GitHub,
through the agent's own gh wrapper, never the operator's credentials.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .config import Config

GIT_TIMEOUT_S = 300


class WorkspaceError(RuntimeError):
    """A git or gh command failed."""


class Workspace:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.env = {**os.environ, "GIT_AUTHOR_NAME": config.commit_name, "GIT_AUTHOR_EMAIL": config.commit_email,
                    "GIT_COMMITTER_NAME": config.commit_name, "GIT_COMMITTER_EMAIL": config.commit_email,
                    "GIT_TERMINAL_PROMPT": "0"}

    def _run(self, args: list[str], cwd: Path) -> str:
        try:
            result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, env=self.env, timeout=GIT_TIMEOUT_S)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise WorkspaceError(f"{args[0]} {args[1]} failed: {error}") from error
        if result.returncode != 0:
            raise WorkspaceError(f"{' '.join(args[:3])} exited {result.returncode}: {result.stderr.strip()[:500]}")
        return result.stdout.strip()

    def git(self, cwd: Path, *args: str) -> str:
        return self._run(["git", *args], cwd)

    @property
    def base_ref(self) -> str:
        return f"origin/{self.config.base_branch}" if self.config.github else self.config.base_branch

    def _credentials(self) -> list[str]:
        assert self.config.github
        return ["-c", "credential.helper=", "-c", f"credential.helper=!{self.config.github.cli} auth git-credential"]

    def prepare(self, ticket_id: str) -> tuple[Path, str]:
        """Creates ``<stateDir>/work/<ticket>`` on branch ``agent/<ticket>`` from the latest base."""
        checkout, branch = self.config.checkout, f"agent/{ticket_id}"
        path = self.config.state_dir / "work" / ticket_id
        if path.exists():
            return path, branch
        if self.config.github:
            self.git(checkout, *self._credentials(), "fetch", "--no-tags", "origin",
                     f"+refs/heads/{self.config.base_branch}:refs/remotes/origin/{self.config.base_branch}")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.git(checkout, "worktree", "add", "-b", branch, str(path), self.base_ref)
        return path, branch

    def uncommitted(self, path: Path) -> list[str]:
        return [line for line in self.git(path, "status", "--porcelain").splitlines() if line.strip()]

    def commits_ahead(self, path: Path) -> int:
        return int(self.git(path, "rev-list", "--count", f"{self.base_ref}..HEAD") or 0)

    def publish(self, path: Path, branch: str, title: str, body: str, draft: bool, pr_url: str) -> str:
        """Pushes the branch and opens or updates its PR; returns the PR URL ('' without GitHub)."""
        if not self.config.github:
            return ""
        gh, repo = self.config.github.cli, self.config.github.repository
        self.git(path, *self._credentials(), "push", "--force-with-lease", "-u", "origin", f"{branch}:{branch}")
        body_file = path.parent / f"{path.name}.pr.md"
        body_file.write_text(body, encoding="utf-8")
        if pr_url:
            self._run([gh, "pr", "edit", pr_url, "--title", title, "--body-file", str(body_file)], path)
            if not draft and self._is_draft(pr_url):
                self._run([gh, "pr", "ready", pr_url], path)
            return pr_url
        args = [gh, "pr", "create", "--repo", repo, "--head", branch, "--base", self.config.base_branch,
                "--title", title, "--body-file", str(body_file)]
        return self._run(args + (["--draft"] if draft else []), path).splitlines()[-1].strip()

    def _is_draft(self, pr_url: str) -> bool:
        assert self.config.github
        out = self._run([self.config.github.cli, "pr", "view", pr_url, "--json", "isDraft", "--jq", ".isDraft"],
                        self.config.checkout)
        return out.strip() == "true"
