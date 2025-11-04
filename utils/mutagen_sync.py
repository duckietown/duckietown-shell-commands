#!/usr/bin/env python3
"""
Tiny Python wrapper around Mutagen (the Go file sync tool).

Features:
- ensure_session(): create or reuse a named sync session
- status(): structured status dict (from `mutagen sync list`)
- pause()/resume()/flush()/terminate()
- monitor(): stream live sync events until Ctrl-C

Requirements:
- `mutagen` installed on PATH (https://mutagen.io)
- The remote (Duckiebot) must be reachable via SSH (key-based auth).
- Use a host path on the robot that is bind-mounted into your container.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
import re
from typing import Dict, List, Optional


class MutagenError(RuntimeError):
    pass


def _run(args: List[str], check: bool = True, capture_json: bool = False, text: bool = True):
    """Run a command. If capture_json=True, parse stdout as JSON. Never raises CalledProcessError."""
    try:
        res = subprocess.run(args, check=False, text=text, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        raise MutagenError("`mutagen` not found on PATH. Install it and try again.")
    if check and res.returncode != 0:
        raise MutagenError(
            f"Command failed: {' '.join(args)}\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
        )
    if capture_json:
        try:
            return json.loads(res.stdout or "{}")
        except json.JSONDecodeError as e:
            raise MutagenError(
                f"Failed to parse JSON from: {' '.join(args)}\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
            ) from e
    return res


@dataclass
class MutagenSession:
    identifier: str
    name: Optional[str]
    status: str
    alpha: str
    beta: str


class MutagenSync:
    """
    High-level helper bound to a session name.
    Example remote URL: ssh://duckie//home/duckietown/dev/duckiebot-project
    """

    def __init__(self, name: str):
        self.name = name
        if shutil.which("mutagen") is None:
            raise MutagenError("`mutagen` not found on PATH. Install it first.")

    # ---------- Query ----------
    def _list_raw(self) -> Dict:
        # Try JSON output first (supported in newer Mutagen releases)
        try:
            return _run(["mutagen", "sync", "list", "--json"], capture_json=True)
        except MutagenError as e:
            msg = str(e).lower()
            if "unknown flag" not in msg and "flag provided but not defined" not in msg:
                # Some other error
                raise
            # Fallback: parse plain-text list output
            res = _run(["mutagen", "sync", "list"], check=True, capture_json=False)
            return self._parse_list_text(res.stdout or "")

    @staticmethod
    def _parse_list_text(text: str) -> Dict:
        """Parse `mutagen sync list` plain text output into a dict similar to --json.

        Example block per session:
            Name: my-session
            Identifier: abc123
            Status: Watching for changes
            Alpha: /path/to/alpha
            Beta: ssh://user@host//path/to/beta
        """
        sessions: List[Dict] = []
        cur: Dict = {}

        def push():
            nonlocal cur
            if cur:
                # Ensure structure keys like JSON
                if isinstance(cur.get("status"), str):
                    cur["status"] = {"description": cur["status"]}
                if isinstance(cur.get("alpha"), str):
                    cur["alpha"] = {"url": cur["alpha"]}
                if isinstance(cur.get("beta"), str):
                    cur["beta"] = {"url": cur["beta"]}
                # Identifier may be missing in old outputs; keep as is
                sessions.append(cur)
                cur = {}

        for raw in (text or "").splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("-") or line.startswith("="):
                # Separator lines
                continue
            if line.lower().startswith("started mutagen daemon"):
                continue
            if line.lower().startswith("no synchronization sessions"):
                # No sessions, bail out
                sessions = []
                break
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key = key.strip().lower()
            val = val.strip()
            if key == "name":
                # New session starts; push previous
                push()
                cur = {"name": val}
            elif key == "identifier":
                cur["identifier"] = val
            elif key == "status":
                cur["status"] = val
            elif key == "alpha":
                cur["alpha"] = val
            elif key == "beta":
                cur["beta"] = val
            else:
                # Ignore other fields
                pass

        # Push last session
        push()
        return {"sessions": sessions}

    def _find_session(self) -> Optional[MutagenSession]:
        data = self._list_raw()
        for s in data.get("sessions", []):
            # Mutagen uses "identifier"; "name" may be absent if created without --name
            name = s.get("name")
            if name == self.name:
                return MutagenSession(
                    identifier=s["identifier"],
                    name=name,
                    status=s.get("status", {}).get("description", "unknown"),
                    alpha=s.get("alpha", {}).get("url", ""),
                    beta=s.get("beta", {}).get("url", ""),
                )
        return None

    def status(self) -> Optional[Dict]:
        """Return full JSON status for this session (or None if not found)."""
        data = self._list_raw()
        for s in data.get("sessions", []):
            if s.get("name") == self.name:
                return s
        return None

    # ---------- Lifecycle ----------
    def ensure_session(
        self,
        alpha: str,
        beta: str,
        ignore_paths: Optional[List[str]] = None,
        symlink_mode: str = "portable",
        mode: str = "two-way-resolved",
        max_staging_file_size: Optional[str] = None,  # e.g., "128MiB"
    ) -> MutagenSession:
        """
        Create the session if it doesn't exist; otherwise reuse it.
        - alpha: local path (e.g., /Users/davide/dev/proj)
        - beta:  remote URL (e.g., ssh://duckie//home/duckietown/dev/proj)
        """
        existing = self._find_session()
        if existing:
            return existing

        base_args = [
            "mutagen",
            "sync",
            "create",
            "--name",
            self.name,
            f"--symlink-mode={symlink_mode}",
            "--ignore-vcs",
        ]
        # Optional flags that might be unsupported in older Mutagen versions
        mode_flag = f"--mode={mode}" if mode else None
        max_stage_flag = f"--max-staging-file-size={max_staging_file_size}" if max_staging_file_size else None
        if ignore_paths:
            # Mutagen supports multiple --ignore options
            for p in ignore_paths:
                base_args += ["--ignore", p]

        # Try a set of endpoint forms for SSH for maximum compatibility
        candidate_betas = _candidate_ssh_endpoints(beta)
        last_error: Optional[Exception] = None
        use_mode = bool(mode_flag)
        use_max_stage = bool(max_stage_flag)
        for cand_beta in candidate_betas:
            args = list(base_args)
            if use_mode and mode_flag:
                args.append(mode_flag)
            if use_max_stage and max_stage_flag:
                args.append(max_stage_flag)
            args += [alpha, cand_beta]

            # Attempt creation with current flags
            while True:
                try:
                    res = _run(args)
                    last_error = None
                    break
                except MutagenError as e:
                    msg = str(e).lower()
                    # Fallbacks for unknown flags
                    if use_mode and ("unknown flag" in msg or "flag provided but not defined" in msg) and "--mode" in " ".join(args):
                        # Remove --mode and retry
                        use_mode = False
                        args = [a for a in args if not a.startswith("--mode=")]
                        continue
                    if use_max_stage and ("unknown flag" in msg or "flag provided but not defined" in msg) and "--max-staging-file-size" in " ".join(args):
                        # Remove --max-staging-file-size and retry
                        use_max_stage = False
                        args = [a for a in args if not a.startswith("--max-staging-file-size=")]
                        continue
                    # Endpoint style issue: try next candidate
                    if "could not resolve hostname ssh" in msg or "unable to dial agent endpoint" in msg:
                        last_error = e
                        break
                    # Other errors: propagate
                    last_error = e
                    break
            if last_error is None:
                # Success
                break

        if last_error is not None:
            raise last_error

        # Re-query to return the new session
        created = self._find_session()
        if not created:
            raise MutagenError(
                "Session creation reported success, but session not found in `mutagen sync list`."
            )
        return created

    def pause(self):
        s = self._find_session()
        if not s:
            return
        _run(["mutagen", "sync", "pause", s.identifier])

    def resume(self):
        s = self._find_session()
        if not s:
            return
        _run(["mutagen", "sync", "resume", s.identifier])

    def flush(self, direction: str = "alpha-to-beta"):
        """
        Force sync in one direction ("alpha-to-beta" or "beta-to-alpha").
        Useful before shutting the laptop or restarting the robot.
        """
        s = self._find_session()
        if not s:
            return
        _run(["mutagen", "sync", "flush", f"--direction={direction}", s.identifier])

    def terminate(self, ignore_errors: bool = True):
        s = self._find_session()
        if not s:
            return
        _run(["mutagen", "sync", "terminate", s.identifier], check=not ignore_errors)

    def monitor(self):
        """
        Stream live events until Ctrl-C.
        """
        s = self._find_session()
        if not s:
            raise MutagenError(f"Session '{self.name}' not found.")
        # Let stdout/stderr stream to the console
        subprocess.run(["mutagen", "sync", "monitor", s.identifier], check=False)


# -------- Version helpers --------

_SEMVER_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def _parse_version(text: str) -> Optional[tuple]:
    m = _SEMVER_RE.search(text.strip())
    if not m:
        return None
    return tuple(int(x) for x in m.groups())


def get_mutagen_version() -> Optional[str]:
    try:
        res = subprocess.run(["mutagen", "version"], check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except FileNotFoundError:
        return None
    out = (res.stdout or "").strip()
    return out or None


def ensure_min_version(min_version: str = "0.17.0"):
    """Ensure mutagen is installed and at least min_version. Raise MutagenError if not."""
    if shutil.which("mutagen") is None:
        raise MutagenError("`mutagen` not found on PATH. Install it first.")
    out = get_mutagen_version()
    if not out:
        raise MutagenError("Unable to determine Mutagen version.")
    cur = _parse_version(out)
    req = _parse_version(min_version)
    if cur is None or req is None:
        # If parsing fails, be conservative and raise
        raise MutagenError(f"Unrecognized Mutagen version string: {out!r}")
    if cur < req:
        raise MutagenError(f"Mutagen {min_version} or newer required; found {out!r}")


# -------- Utilities --------
def sanitize_session_name(name: str) -> str:
    """Return a Mutagen-compliant session name (letters, digits, _ and -).

    Replaces any other character with '-'. Collapses consecutive dashes and trims edges.
    """
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", name)
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    return cleaned or "dts-sync"


def _candidate_ssh_endpoints(beta: str) -> List[str]:
    """Return a list of SSH endpoint variants to maximize compatibility across Mutagen versions.

    Accepts inputs like:
      - ssh://user@host//abs/path
      - user@host:/abs/path
      - ssh:user@host:/abs/path

    Returns a list starting with the given value (normalized), followed by alternates.
    """
    beta = beta.strip()
    cands: List[str] = []
    if beta.startswith("ssh://"):
        rest = beta[len("ssh://"):]
        user = ""
        if "@" in rest:
            user, rest = rest.split("@", 1)
            user = f"{user}@"
        # rest is like host//abs/path or host/rel
        if "/" in rest:
            host, path = rest.split("/", 1)
        else:
            host, path = rest, ""
        # derive absolute path
        if path.startswith("/"):
            abs_path = path
        elif path.startswith("//"):
            abs_path = "/" + path.lstrip("/")
        else:
            abs_path = "/" + path
        # Normalize
        ssh_scheme = f"ssh://{user}{host}//{abs_path.lstrip('/')}"
        scp_style = f"{user}{host}:{abs_path}"
        ssh_colon = f"ssh:{user}{host}:{abs_path}"
        # Build list without duplicates
        for v in [ssh_scheme, scp_style, ssh_colon]:
            if v and v not in cands:
                cands.append(v)
        return cands
    else:
        # Already scp-style or ssh: style; try as-is then add alternates
        cands.append(beta)
        # Try to convert scp-style to ssh://
        # Expect form user@host:/abs/path
        if ":" in beta and "/" in beta.split(":", 1)[1]:
            left, path = beta.split(":", 1)
            user = ""
            host = left
            if "@" in left:
                user, host = left.split("@", 1)
                user = f"{user}@"
            ssh_scheme = f"ssh://{user}{host}//{path.lstrip('/')}"
            ssh_colon = f"ssh:{user}{host}:/{path.lstrip('/')}"
            for v in [ssh_scheme, ssh_colon]:
                if v and v not in cands:
                    cands.append(v)
        return cands
