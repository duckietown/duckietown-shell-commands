#!/usr/bin/env python3
"""
Rsync-based synchronization for Duckietown projects.

Features:
- One-time sync using rsync over SSH
- Supports ignore patterns
- Uses SSH config for authentication
"""

import os
import subprocess
from typing import List, Optional
from dt_shell import dtslogger


class RsyncError(RuntimeError):
    pass


def rsync_sync(
    local_path: str,
    remote_user: str,
    remote_host: str,
    remote_path: str,
    ignore_patterns: Optional[List[str]] = None,
    verbose: bool = False,
) -> None:
    """
    Sync a local directory to a remote host using rsync over SSH.

    Args:
        local_path: Local directory to sync
        remote_user: Username on remote host
        remote_host: Remote hostname or IP
        remote_path: Destination directory on remote host
        ignore_patterns: List of patterns to exclude (e.g., ".git/", "*.pyc")
        verbose: Enable verbose output
    """
    # Ensure local path exists and is a directory
    if not os.path.isdir(local_path):
        raise RsyncError(f"Local path does not exist or is not a directory: {local_path}")

    # Ensure remote directory exists
    mkdir_cmd = ["ssh", f"{remote_user}@{remote_host}", f"mkdir -p '{remote_path}'"]
    try:
        subprocess.run(mkdir_cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        stderr_msg = e.stderr if e.stderr else "unknown error"
        raise RsyncError(f"Failed to create remote directory: {stderr_msg}")

    # Build rsync command
    # -a: archive mode (recursive, preserves permissions, times, etc.)
    # -z: compress during transfer
    # -v: verbose (optional)
    # --delete: delete files on remote that don't exist locally
    rsync_cmd = ["rsync", "-az"]

    if verbose:
        rsync_cmd.append("-v")
    else:
        rsync_cmd.append("--quiet")

    # Add delete flag to keep remote in sync
    rsync_cmd.append("--delete")

    # Add exclude patterns
    if ignore_patterns:
        for pattern in ignore_patterns:
            rsync_cmd.extend(["--exclude", pattern])

    # Ensure local path ends with / to sync contents, not the directory itself
    if not local_path.endswith("/"):
        local_path = local_path + "/"

    # Add source and destination
    rsync_cmd.append(local_path)
    rsync_cmd.append(f"{remote_user}@{remote_host}:{remote_path}")

    # Execute rsync
    dtslogger.debug(f"Running rsync: {' '.join(rsync_cmd)}")
    try:
        result = subprocess.run(rsync_cmd, check=True, capture_output=True, text=True)
        if verbose and result.stdout:
            dtslogger.info(result.stdout)
    except subprocess.CalledProcessError as e:
        error_msg = f"Rsync failed: {e.stderr}"
        dtslogger.error(error_msg)
        raise RsyncError(error_msg)
    except FileNotFoundError:
        raise RsyncError(
            "rsync command not found. Please install rsync:\n"
            "  - Ubuntu/Debian: sudo apt-get install rsync\n"
            "  - macOS: brew install rsync\n"
            "  - Windows: Install WSL or use Cygwin"
        )

    dtslogger.info(f"Synced {local_path} to {remote_user}@{remote_host}:{remote_path}")
