import argparse

import docker
from dt_shell import DTCommandAbs, dtslogger
from dt_shell.env_checks import check_docker_environment
from utils.cli_utils import start_command_in_subprocess
from utils.docker_utils import bind_duckiebot_data_dir, default_env, remove_if_running, pull_if_not_exist
from utils.networking_utils import get_duckiebot_ip

usage = """

## Basic usage


    To find out more, use `dts duckiebot mooc -h`.

        $ dts mooc submit --exercise_path [EXERCISE_PATH]

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
        mooc_name = parsed.mooc_name
        if mooc_name is None:
            msg = "You must specify a path"
            raise InvalidUserInput(msg)

        # if we run in experimental mode - change the default
        # image and package. Note: in experimental mode you cannot
        # explicitly choose the default image and package because they will
        # be overwritten here.
        if parsed.experimental and parsed.image_to_run == DEFAULT_IMAGE:
            parsed.image_to_run = EXPERIMENTAL_IMAGE

        if parsed.experimental and parsed.package_name == DEFAULT_PACKAGE:
            parsed.packge_name = EXPERIMENTAL_PACKAGE

        duckiebot_name = parsed.duckiebot_name
        if duckiebot_name is None:
            msg = "You must specify a duckiebot_name"
            raise InvalidUserInput(msg)

        package_name = parsed.package_name
        dtslogger.info("Using package %s" % package_name)

        duckiebot_ip = get_duckiebot_ip(duckiebot_name)
        if parsed.local:
            duckiebot_client = check_docker_environment()
        else:
            # noinspection PyUnresolvedReferences
            duckiebot_client = docker.DockerClient("tcp://" + duckiebot_ip + ":2375")

        container_name = "mooc_%s" % mooc_name
        remove_if_running(duckiebot_client, container_name)
        image_base = parsed.image_to_run
        env_vars = default_env(duckiebot_name, duckiebot_ip)
        env_vars.update({
            "VEHICLE_NAME": duckiebot_name,
            "VEHICLE_IP": duckiebot_ip
        })

        if mooc_name == "base":
            cmd = "/bin/bash"
        else:
            cmd = "roslaunch %s %s.launch veh:=%s" % (
                package_name,
                mooc_name,
                duckiebot_name,
            )

        pull_if_not_exist(duckiebot_client, image_base)

        dtslogger.info("Running command %s" % cmd)
        mooc_container = duckiebot_client.containers.run(
            image=image_base,
            command=cmd,
            network_mode="host",
            volumes=bind_duckiebot_data_dir(),
            privileged=True,
            name=container_name,
            mem_limit="800m",
            memswap_limit="2800m",
            stdin_open=True,
            tty=True,
            detach=True,
            environment=env_vars,
        )

        if mooc_name == "base" or parsed.debug:
            attach_cmd = "docker -H %s.local attach %s" % (
                duckiebot_name,
                container_name,
            )
            start_command_in_subprocess(attach_cmd)
