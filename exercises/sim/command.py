import argparse

import docker
from dt_shell import DTCommandAbs, dtslogger
from dt_shell.env_checks import check_docker_environment
from utils.cli_utils import start_command_in_subprocess
from utils.docker_utils import bind_duckiebot_data_dir, default_env, remove_if_running, pull_if_not_exist, build_if_not_exist
from utils.networking_utils import get_duckiebot_ip


import nbformat  # install before?
from nbconvert.exporters import PythonExporter

#from git import Repo # pip install gitpython 
import os
from shutil import copyfile

import yaml

usage = """

## Basic usage
    This is an helper for the MOOC classes, it tests the exercise on your Duckiebot. 
    You must run this command inside the exercise folder. 

    To know more on the `mooc` commands, use `dts duckiebot mooc -h`.

        $ dts duckiebot mooc sim

"""

MOOC_IMAGE = 'duckietown/mooc-exercises:exercise'

class InvalidUserInput(Exception):
    pass


from dt_shell import DTShell


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        pass
        #TODO...

def convertNotebook(filepath,export_path) -> bool:
    if not os.path.exists(filepath):
        return False
    nb = nbformat.read(filepath, as_version=4)    
    exporter = PythonExporter()

    # source is a tuple of python source code
    # meta contains metadata
    source, _ = exporter.from_notebook_node(nb)
    try :
        with open(export_path, 'w+') as fh:
            fh.writelines(source)
    except Exception:
        return False
    
    return True
    
