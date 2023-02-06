import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import List

import requests
from dt_shell import dtslogger, DTShell
from dt_shell.utils import run_cmd

from utils.duckietown_utils import get_distro_version


@dataclass
class CommitInfo:
    sha: str
    url: str
    date: datetime


@dataclass
class UpdateResult:
    commit: CommitInfo
    uptodate: bool


def clone_repository(repo: str, branch: str, destination: str):
    remote_url: str = f"https://github.com/{repo}"
    try:
        run_cmd(["git", "clone", "-b", branch, "--recurse-submodules", remote_url, destination])
    except Exception as e:
        # Excepts as InvalidRemote
        dtslogger.error(f"Unable to clone the repo '{repo}'. {str(e)}.")
        return False


def get_branches(user: str, repo: str) -> List:
    url = f"https://api.github.com/repos/{user}/{repo}/branches"
    response = requests.get(url)
    if response.status_code >= 400:
        msg = f"Cannot get branch list from github API ({response.status_code}) "
        raise Exception(msg)
    res = response.json()

    branches = [branch["name"] for branch in res]
    return branches


def get_last_commit(user: str, repo: str, branch: str) -> CommitInfo:
    url = f"https://api.github.com/repos/{user}/{repo}/branches/{branch}"
    response = requests.get(url)
    if response.status_code >= 400:
        msg = f"Cannot get commit from github API ({response.status_code}) "
        raise Exception(msg)
    res = response.json()
    commit = res["commit"]
    dtslogger.debug(json.dumps(res, indent=2))
    sha = commit["sha"]
    url = commit["url"]

    import dateutil.parser

    date_time_str = commit["commit"]["author"]["date"]
    # 2012-03-06T23:06:50Z
    # d = datetime.fromisoformat(date_time_str)
    d = dateutil.parser.parse(date_time_str)
    return CommitInfo(sha, url, d)


def check_up_to_date(shell: DTShell, repo: str) -> UpdateResult:
    dtslogger.debug("Checking for updated exercises")
    ci = get_last_commit("duckietown", repo, get_distro_version(shell))

    cmd = "git", "merge-base", "--is-ancestor", ci.sha, "HEAD"
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError:
        ok = False
    else:
        ok = True

    return UpdateResult(ci, ok)
