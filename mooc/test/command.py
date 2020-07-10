import argparse

import docker
from dt_shell import DTCommandAbs, dtslogger
from dt_shell.env_checks import check_docker_environment
from utils.cli_utils import start_command_in_subprocess
from utils.docker_utils import bind_duckiebot_data_dir, default_env, remove_if_running, pull_if_not_exist, build_if_not_exist
from utils.networking_utils import get_duckiebot_ip


import nbformat  # install before?
from IPython.nbconvert import PythonExporter

from git import Repo # pip install gitpython 
import os
from shutil import copyfile

usage = """

## Basic usage
    This is an helper for the MOOC classes. You can test the exrecises specifing the path 
    to the exercise folder and your Duckiebot name.

    To find out more, use `dts duckiebot mooc -h`.

        $ dts duckiebot mooc --exercise_path [EXERCISE_PATH] --duckiebot_name [DUCKIEBOT_NAME]

"""

MOOC_IMAGE = 'duckietown/mooc-exercises:exercise'

class InvalidUserInput(Exception):
    pass


from dt_shell import DTShell


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts duckiebot mooc"
        parser = argparse.ArgumentParser(prog=prog, usage=usage)

        parser.add_argument(
            "--exercise_path", '-d',
            dest="exercise_path",
            default=None,
            help="Path to the exercise folder",
        )

        parser.add_argument(
            "--duckiebot_name", '-b',
            dest="duckiebot_name",
            default=None,
            help="Name of the Duckiebot on which to run the exercise",
        )

        parsed = parser.parse_args(args)

        check_docker_environment()
        exercise_path = parsed.exercise_path
        if exercise_path is None:
            msg = "You must specify a path"
            raise InvalidUserInput(msg)

        duckiebot_name = parsed.duckiebot_name
        if duckiebot_name is None:
            msg = "You must specify a duckiebot_name"
            raise InvalidUserInput(msg)

        if not cloneRepo(exercise_path):
            raise Exception("Error in cloning the repo")

        repo_path = exercise_path +"/mooc-exercises"

        # convert the notebook to py and copy into the Image
        if not convertNotebook(exercise_path+"/1_develop/notebooks/exercise.ipynb",repo_path+"/packages/mooc/src/exercise.py"):
            raise Exception("Make sure the path to the exercise folder is correct ...")
        #
        #   It would be great to have only one repo and then clone in it 
        #   different packages according to a file present in the exercise folder
        #

        #
        #   buid and run the image on the DB
        #

        duckiebot_ip = get_duckiebot_ip(duckiebot_name)
        duckiebot_client = docker.DockerClient("tcp://" + duckiebot_ip + ":2375")

        remove_if_running(duckiebot_client, "mooc")
        
        env_vars = default_env(duckiebot_name, duckiebot_ip)
        env_vars.update({
            "VEHICLE_NAME": duckiebot_name,
            "VEHICLE_IP": duckiebot_ip
        })

        build_if_not_exist(duckiebot_client,repo_path,'duckietown/mooc')

        cmd = "roslaunch mooc mooc.launch veh:=%s" % (
                duckiebot_name,
        )
        dtslogger.info("Running command %s" % cmd)
        demo_container = duckiebot_client.containers.run(
            image="duckietown/mooc",
            command=cmd,
            network_mode="host",
            volumes=bind_duckiebot_data_dir(),
            privileged=True,
            name="mooc",
            mem_limit="800m",
            memswap_limit="2800m",
            stdin_open=True,
            tty=True,
            detach=True,
            environment=env_vars,
        )
        
        print("Process completed successfully!")
    

def cloneRepo(full_path) -> bool:
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
            Repo.clone_from(git_repo, clone_path, branch="duckiebot-test-image")
            dtslogger.info('Cloning complete for repo {}'.format(name))
            return True
        except Exception as e:
            dtslogger.error('Unable to clone repo {}. Reason: {} '.format(name, str(e)))

    return False

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
    
