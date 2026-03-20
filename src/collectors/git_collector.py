"""Git-based project collector.

For non-trading projects (Equity Engine, Auto Research).
Reads git log and latest handoff file.
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

            if os.path.isdir(base):
                self._read_git_log(base, metrics)
                self._read_latest_handoff(base, metrics)
            else:
                # Repo not cloned on VPS — try GitHub API
                github_repo = self.config.get("github_repo")
                if github_repo:
                    self._read_from_github(github_repo, metrics)
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
            # Read first 20 lines for summary
            lines = []
            for i, line in enumerate(f):
                if i >= 20:
                    break
                lines.append(line.strip())

        # Extract title from filename or first heading
        filename = os.path.basename(latest)
        for line in lines:
            if line.startswith("# "):
                metrics.handoff_summary = line[2:].strip()
                break
        if not metrics.handoff_summary:
            metrics.handoff_summary = filename.replace(".md", "").replace("_", " ")

    def _read_from_github(self, repo: str, metrics: ProjectMetrics):
        """Fallback: use gh CLI to get latest commit."""
        result = subprocess.run(
            ["gh", "api", f"repos/{repo}/commits", "-q", ".[0] | .sha[:8] + \"|\" + .commit.author.date + \"|\" + .commit.message"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split("|", 2)
            if len(parts) >= 3:
                metrics.last_commit_date = datetime.fromisoformat(parts[1].replace("Z", "+00:00"))
                metrics.last_commit_message = parts[2].split("\n")[0]  # First line only
                days_ago = (datetime.utcnow() - metrics.last_commit_date.replace(tzinfo=None)).days
                metrics.status_text = f"Last commit {days_ago}d ago: {metrics.last_commit_message}"
        else:
            metrics.healthy = False
            metrics.error = f"GitHub API failed for {repo}"
            metrics.status_text = "UNKNOWN"
