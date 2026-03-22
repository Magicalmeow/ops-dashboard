"""Git-based project collector.

For non-trading projects (Equity Engine, Auto Research).
Reads git log and latest handoff file. Falls back to GitHub API via curl.
"""

import glob
import os
import subprocess
from datetime import datetime

from src.collectors.base import BaseCollector
from src.models import ProjectMetrics


class GitCollector(BaseCollector):

    def collect(self) -> ProjectMetrics:
        metrics = ProjectMetrics(
            project_name=self.name,
            collector_type=self.config["collector_type"],
        )
        try:
            base = self.config["base_path"]

            if os.path.isdir(os.path.join(base, ".git")):
                self._read_git_log(base, metrics)
                self._read_latest_handoff(base, metrics)
            elif os.path.isdir(base):
                # Directory exists but not a git repo
                self._read_latest_handoff(base, metrics)
                if not metrics.status_text:
                    metrics.status_text = "Directory exists but not a git repo"
            else:
                # Repo not on VPS — try GitHub API via curl
                github_repo = self.config.get("github_repo")
                if github_repo:
                    self._read_from_github_curl(github_repo, metrics)
                else:
                    metrics.healthy = False
                    metrics.error = f"Repo not found at {base}"
                    metrics.status_text = "NOT DEPLOYED"

        except Exception as e:
            metrics.healthy = False
            metrics.error = str(e)

        return metrics

    def _read_git_log(self, repo_path: str, metrics: ProjectMetrics):
        """Read latest commit info via git."""
        result = subprocess.run(
            ["git", "-C", repo_path, "log", "-1", "--format=%H|%aI|%s"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split("|", 2)
            if len(parts) >= 3:
                metrics.last_commit_date = datetime.fromisoformat(parts[1])
                metrics.last_commit_message = parts[2]

        # Current branch
        result = subprocess.run(
            ["git", "-C", repo_path, "branch", "--show-current"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            metrics.branch = result.stdout.strip()

        if metrics.last_commit_date:
            days_ago = (datetime.utcnow() - metrics.last_commit_date.replace(tzinfo=None)).days
            metrics.status_text = f"Last commit {days_ago}d ago: {metrics.last_commit_message}"

    def _read_latest_handoff(self, repo_path: str, metrics: ProjectMetrics):
        """Read the most recent handoff file for summary context."""
        handoff_dir = os.path.join(repo_path, "handoffs")
        if not os.path.isdir(handoff_dir):
            return

        handoffs = sorted(glob.glob(os.path.join(handoff_dir, "*.md")))
        if not handoffs:
            return

        latest = handoffs[-1]
        with open(latest, "r") as f:
            lines = []
            for i, line in enumerate(f):
                if i >= 20:
                    break
                lines.append(line.strip())

        for line in lines:
            if line.startswith("# "):
                metrics.handoff_summary = line[2:].strip()
                break
        if not metrics.handoff_summary:
            filename = os.path.basename(latest)
            metrics.handoff_summary = filename.replace(".md", "").replace("_", " ")

    def _read_from_github_curl(self, repo: str, metrics: ProjectMetrics):
        """Fallback: use curl + GitHub API to get latest commit (no gh CLI needed)."""
        cmd = ["curl", "-sf"]
        token = os.environ.get("GITHUB_TOKEN", "")
        if token:
            cmd.extend(["-H", f"Authorization: token {token}"])
        cmd.append(f"https://api.github.com/repos/{repo}/commits?per_page=1")
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            import json
            try:
                commits = json.loads(result.stdout)
                if commits and len(commits) > 0:
                    commit = commits[0]
                    date_str = commit["commit"]["author"]["date"]
                    metrics.last_commit_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    metrics.last_commit_message = commit["commit"]["message"].split("\n")[0]
                    days_ago = (datetime.utcnow() - metrics.last_commit_date.replace(tzinfo=None)).days
                    metrics.status_text = f"Last commit {days_ago}d ago: {metrics.last_commit_message}"
                    return
            except (json.JSONDecodeError, KeyError, IndexError):
                pass

        metrics.status_text = f"GitHub API check failed for {repo}"
