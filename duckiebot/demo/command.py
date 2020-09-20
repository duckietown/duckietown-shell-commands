import argparse

import docker
from dt_shell import DTCommandAbs, dtslogger
from dt_shell.env_checks import check_docker_environment
from utils.cli_utils import start_command_in_subprocess
from utils.docker_utils import bind_duckiebot_data_dir, default_env, remove_if_running, pull_if_not_exist
from utils.networking_utils import get_duckiebot_ip

usage = """

## Basic usage

    Runs a demo on the Duckiebot. Effectively, this is a wrapper around roslaunch. You
    can specify a docker image, ros package and launch file to be started. A demo is a
    launch file specified by `--demo_name`. The argument `--package_name` specifies
    the package where the launch file should is located (by default assumes `duckietown`).

    To find out more, use `dts duckiebot demo -h`.

        $ dts duckiebot demo --demo_name [DEMO_NAME] --duckiebot_name [DUCKIEBOT_NAME]

"""
ARCH = "arm32v7"
BRANCH = "daffy"
DEFAULT_IMAGE = "duckietown/dt-core:" + BRANCH + "-" + ARCH
EXPERIMENTAL_IMAGE = "duckietown/dt-experimental:" + BRANCH + "-" + ARCH
DEFAULT_PACKAGE = "duckietown_demos"
EXPERIMENTAL_PACKAGE = "experimental_demos"


class InvalidUserInput(Exception):
    pass


from dt_shell import DTShell


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts duckiebot demo"
        parser = argparse.ArgumentParser(prog=prog, usage=usage)

        parser.add_argument(
            "--demo_name", "-d", dest="demo_name", default=None, help="Name of the demo to run",
        )

        parser.add_argument(
            "--duckiebot_name",
            "-b",
            dest="duckiebot_name",
            default=None,
            help="Name of the Duckiebot on which to run the demo",
        )

        parser.add_argument(
            "--package_name",
            "-p",
            dest="package_name",
            default=DEFAULT_PACKAGE,
            help="You can specify the package that you want to use to look for launch files",
        )

        parser.add_argument(
            "--image",
            "-i",
            dest="image_to_run",
            default=DEFAULT_IMAGE,
            help="Docker image to use, you probably don't need to change ",
        )

        parser.add_argument(
            "--debug",
            "-g",
            dest="debug",
            action="store_true",
            default=False,
            help="will enter you into the running container",
        )

        parser.add_argument(
            "--experimental",
            "-e",
            dest="experimental",
            action="store_true",
            default=False,
            help="you can use this if your demo is in the `experimental` repo. "
            + "It will pick the image from the experimental repo and it will"
            + "default the package name to experimental_demos",
        )

        parser.add_argument(
            "--local",
            "-l",
            dest="local",
            action="store_true",
            default=False,
            help="Run the demo on this machine",
        )

        parsed = parser.parse_args(args)

        check_docker_environment()
        demo_name = parsed.demo_name
        if demo_name is None:
            msg = "You must specify a demo_name"
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

        container_name = "demo_%s" % demo_name
        remove_if_running(duckiebot_client, container_name)
        image_base = parsed.image_to_run
        env_vars = default_env(duckiebot_name, duckiebot_ip)
        env_vars.update({"VEHICLE_NAME": duckiebot_name, "VEHICLE_IP": duckiebot_ip})

        if demo_name == "base":
            cmd = "/bin/bash"
        else:
            cmd = "roslaunch %s %s.launch veh:=%s" % (package_name, demo_name, duckiebot_name,)

        pull_if_not_exist(duckiebot_client, image_base)

        dtslogger.info("Running command %s" % cmd)
        demo_container = duckiebot_client.containers.run(
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

        if demo_name == "base" or parsed.debug:
            attach_cmd = "docker -H %s.local attach %s" % (duckiebot_name, container_name,)
            start_command_in_subprocess(attach_cmd)
