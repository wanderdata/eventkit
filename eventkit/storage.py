"""Where a series folder is kept between runs.

LocalStore  a folder on disk (laptop, an ECLAC server).
GitStore    a private Git repository (e.g. github.com/<you>/event-tracker-data) that the
            app clones on start and pushes to after every change. Hosted apps such as
            Streamlit Community Cloud lose their disk on restart, so this keeps the
            uploaded files, articles and stats safe and versioned.

Choose with environment variables (or Streamlit secrets):
    EVENTKIT_DATA_REPO   owner/repo of the data repository   → GitStore
    EVENTKIT_DATA_TOKEN  token with read/write access to that repo only
    EVENTKIT_DATA_BRANCH branch (default main)
    EVENTKIT_HOME        folder to use when no data repo is set → LocalStore
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

_LOCK = threading.Lock()


class LocalStore:
    kind = "local"

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def sync(self):
        return self.root

    def save(self, message: str):
        return False

    def describe(self) -> str:
        return f"carpeta local {self.root}"


class GitStore:
    kind = "git"

    def __init__(self, url: str, branch: str = "main", root: Path | None = None,
                 author=("eventkit app", "eventkit@noreply.local"), display: str | None = None):
        self.url = url
        self.branch = branch
        self.root = Path(root or Path(tempfile.gettempdir()) / "eventkit-data").resolve()
        self.author = author
        self.display = display or url.split("@")[-1]

    # -- helpers
    def _git(self, *args, check=True, cwd=None):
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0",
               "GIT_AUTHOR_NAME": self.author[0], "GIT_AUTHOR_EMAIL": self.author[1],
               "GIT_COMMITTER_NAME": self.author[0], "GIT_COMMITTER_EMAIL": self.author[1]}
        r = subprocess.run(["git", *args], cwd=cwd or self.root, env=env, text=True, capture_output=True)
        if check and r.returncode != 0:
            msg = (r.stderr or r.stdout).replace(self.url, self.display)
            raise RuntimeError(f"git {args[0]} failed: {msg.strip()}")
        return r

    def _remote_has_branch(self) -> bool:
        r = self._git("ls-remote", "--heads", self.url, self.branch, check=False, cwd=self.root.parent)
        return bool(r.stdout.strip())

    # -- API
    def sync(self) -> Path:
        """Clone on first use, afterwards hard-reset to the remote (the repo is the source of truth)."""
        with _LOCK:
            if not (self.root / ".git").exists():
                if self.root.exists():
                    shutil.rmtree(self.root)
                self.root.parent.mkdir(parents=True, exist_ok=True)
                if self._remote_has_branch():
                    self._git("clone", "--branch", self.branch, self.url, str(self.root), cwd=self.root.parent)
                else:  # empty repository: start a new history
                    self.root.mkdir(parents=True)
                    self._git("init", "-b", self.branch)
                    self._git("remote", "add", "origin", self.url)
            gi = self.root / ".gitignore"
            if not gi.exists():
                gi.write_text("public/\n.eventkit_salt\n__pycache__/\n")
            elif self._remote_has_branch():
                self._git("fetch", "origin", self.branch)
                self._git("reset", "--hard", f"origin/{self.branch}")
                self._git("clean", "-fd", "-e", ".eventkit_salt")
        return self.root

    def save(self, message: str) -> bool:
        """Commit everything and push; retries once on a concurrent update."""
        with _LOCK:
            self._git("add", "-A")
            if self._git("diff", "--cached", "--quiet", check=False).returncode == 0:
                return False
            self._git("commit", "-m", message)
            r = self._git("push", "origin", f"HEAD:{self.branch}", check=False)
            if r.returncode != 0:
                self._git("pull", "--rebase", "origin", self.branch)
                self._git("push", "origin", f"HEAD:{self.branch}")
            return True

    def describe(self) -> str:
        return f"repositorio {self.display} (rama {self.branch})"


def _setting(name: str, default=None):
    return os.environ.get(name, default)


def get_store() -> LocalStore | GitStore:
    repo = _setting("EVENTKIT_DATA_REPO")
    if repo:
        token = _setting("EVENTKIT_DATA_TOKEN", "")
        if repo.startswith(("http://", "https://", "file://", "/")):
            url = repo
        else:
            auth = f"x-access-token:{token}@" if token else ""
            url = f"https://{auth}github.com/{repo}.git"
        return GitStore(url, branch=_setting("EVENTKIT_DATA_BRANCH", "main"),
                        root=_setting("EVENTKIT_CACHE_DIR"), display=repo)
    return LocalStore(Path(_setting("EVENTKIT_HOME", "event-data")))
