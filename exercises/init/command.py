import argparse
import os

from dt_shell import DTCommandAbs, DTShell, dtslogger

usage = """

## Basic usage
    This is an helper for the MOOC classes, it download and initialize the repository for the MOOC exercises.

    To know more on the `exercises` commands, use `dts exercises -h`.

        $ dts exercises init

"""

repo_team = "duckietown"
repo_name = "dt-exercises"


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts exercises init"
        argparse.ArgumentParser(prog=prog, usage=usage)
        working_dir = os.getcwd()
        cloneRepo(working_dir)
        dtslogger.info("Exercise repo initialized sucessfully")


def cloneRepo(full_path) -> bool:
    from git import Repo  # pip install gitpython

    clone_path = os.path.abspath(os.path.join(full_path, repo_name))

    if os.path.exists(clone_path):
        dtslogger.info("Repo already exists")
        return True
    else:
        print("Cloning repo {}".format(repo_name))
        try:
            git_repo = "https://github.com/{}/{}.git".format(repo_team, repo_name)
            Repo.clone_from(git_repo, clone_path, branch="daffy", recursive=True)
            dtslogger.info("Cloning complete for repo {}".format(repo_name))
            return True
        except Exception as e:
            dtslogger.error("Unable to clone repo {}. Reason: {} ".format(repo_name, str(e)))
    return False
