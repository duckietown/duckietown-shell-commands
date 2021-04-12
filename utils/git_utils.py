import json
import subprocess
from dataclasses import dataclass
from datetime import datetime

import requests
from dt_shell import dtslogger


@dataclass
class CommitInfo:
    sha: str
    url: str
    date: datetime


@dataclass
class UpdateResult:
    commit: CommitInfo
    uptodate: bool


def get_last_commit(user: str, repo: str, branch: str) -> CommitInfo:
    url = f'https://api.github.com/repos/{user}/{repo}/branches/{branch}'
    response = requests.get(url)
    if response.status_code >= 400:
        msg = f'Cannot get commit from github API ({response.status_code}) '
        raise Exception(msg)
    res = response.json()
    commit = res['commit']
    dtslogger.debug(json.dumps(res, indent=2))
    sha = commit['sha']
    url = commit['url']

    import dateutil.parser

    date_time_str = commit['commit']['author']['date']
    # 2012-03-06T23:06:50Z
    # d = datetime.fromisoformat(date_time_str)
    d = dateutil.parser.parse(date_time_str)
    return CommitInfo(sha, url, d)


def check_up_to_date() -> UpdateResult:
    dtslogger.debug('Checking for updated exercises')
    ci = get_last_commit('duckietown', 'mooc-exercises', 'daffy')


    cmd = "git", "merge-base", "--is-ancestor", ci.sha, "HEAD"
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError:
        ok = False
    else:
        ok = True

    return UpdateResult(ci, ok)
