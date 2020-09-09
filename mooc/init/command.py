import argparse

import docker
from dt_shell import DTCommandAbs, dtslogger
from dt_shell.env_checks import check_docker_environment
from utils.cli_utils import start_command_in_subprocess
from utils.docker_utils import bind_duckiebot_data_dir, default_env, remove_if_running, pull_if_not_exist, build_if_not_exist
from utils.networking_utils import get_duckiebot_ip

#from git import Repo # pip install gitpython 
import os
from shutil import copyfile

import yaml

usage = """

## Basic usage
    This is an helper for the MOOC classes, it download and initialize the repository for the MOOC exercises. 

    To know more on the `mooc` commands, use `dts duckiebot mooc -h`.

        $ dts duckiebot mooc init

"""

class InvalidUserInput(Exception):
    pass


from dt_shell import DTShell


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts mooc init"
        argparse.ArgumentParser(prog=prog, usage=usage)

        #
        #   get current working directory
        #
        working_dir = os.getcwd()
        cloneRepo(working_dir)


        os.system('cd '+working_dir+'/mooc-exercises && make start')

        dtslogger.info("Exercise repo initialized sucessfully")


def cloneRepo(full_path) -> bool:
    from git import Repo # pip install gitpython 

    name = "mooc-exercises"
    team = "duckietown"
    
    clone_path = os.path.abspath(os.path.join(full_path, name))

    if os.path.exists(clone_path):
        dtslogger.info("Repo already exists")
        return True
    else:
        print('Cloning repo {}'.format(name))
        try:
            git_repo = 'https://github.com/{}/{}.git'.format(team, name)
            Repo.clone_from(git_repo, clone_path, branch="daffy", recursive=True)
            dtslogger.info('Cloning complete for repo {}'.format(name))
            return True
        except Exception as e:
            dtslogger.error('Unable to clone repo {}. Reason: {} '.format(name, str(e)))

    return False
