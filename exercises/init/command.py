import argparse
import os

from dt_shell import DTCommandAbs, DTShell, dtslogger, UserError

usage = """

## Basic usage
    This is an helper for the MOOC classes, it download and initialize the repository for the MOOC exercises.

    To know more on the `exercises` commands, use `dts duckiebot exercises -h`.

        $ dts duckiebot exercises init

"""


class InvalidUserInput(UserError):
    pass


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts exercises init"
        argparse.ArgumentParser(prog=prog, usage=usage)

        #
        #   get current working directory
        #
        working_dir = os.getcwd()
        cloneRepo(working_dir)

        os.system("cd " + working_dir + "/mooc-exercises && make start")

        dtslogger.info("Exercise repo initialized sucessfully")


def cloneRepo(full_path) -> bool:
    from git import Repo  # pip install gitpython

    name = "dt-exercises"
    team = "duckietown"

    clone_path = os.path.abspath(os.path.join(full_path, name))

    if os.path.exists(clone_path):
        dtslogger.info("Repo already exists")
        return True
    else:
        print("Cloning repo {}".format(name))
        try:
            git_repo = "https://github.com/{}/{}.git".format(team, name)
            Repo.clone_from(git_repo, clone_path, branch="daffy", recursive=True)
            dtslogger.info("Cloning complete for repo {}".format(name))
            return True
        except Exception as e:
            dtslogger.error("Unable to clone repo {}. Reason: {} ".format(name, str(e)))

    return False
