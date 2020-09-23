import argparse

import docker
from dt_shell import DTCommandAbs, dtslogger
from dt_shell.env_checks import check_docker_environment
from utils.avahi_utils import wait_for_service
from utils.cli_utils import start_command_in_subprocess
from utils.docker_utils import bind_duckiebot_data_dir, default_env, remove_if_running, pull_if_not_exist
from utils.networking_utils import get_duckiebot_ip

from dt_shell import DTShell


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
EXPERIMENTAL_PACKAGE = "experimental_demos"


class InvalidUserInput(Exception):
    pass


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts duckiebot demo"
        parser = argparse.ArgumentParser(prog=prog, usage=usage)

        parser.add_argument(
            "--demo_name",
            "-d",
            dest="demo_name",
            default=None,
            help="Name of the demo to run"
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
            default=None,
            help="You can specify the package that you want to use to look for launch files",
        )

        parser.add_argument(
            "--robot_type", '-t',
            dest="robot_type",
            default='auto',
            help="The robot type",
        )

        parser.add_argument(
            "--robot_configuration", '-c',
            dest="robot_configuration",
            default='auto',
            help="The robot configuration",
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

        if parsed.demo_name is None:
            if parsed.package_name is not None:
                msg = "You must specify a --demo_name together with the --package_name option."
                dtslogger.error(msg)
                exit(1)
            else:
                parsed.demo_name = 'default'

        # if we run in experimental mode - change the default
        # image and package. Note: in experimental mode you cannot
        # explicitly choose the default image and package because they will
        # be overwritten here.
        if parsed.experimental and parsed.image_to_run == DEFAULT_IMAGE:
            parsed.image_to_run = EXPERIMENTAL_IMAGE

        if parsed.experimental and parsed.package_name is None:
            parsed.package_name = EXPERIMENTAL_PACKAGE

        duckiebot_name = parsed.duckiebot_name
        if duckiebot_name is None:
            msg = "You must specify a duckiebot_name"
            raise InvalidUserInput(msg)

        if parsed.package_name:
            dtslogger.info("Using package %s" % parsed.package_name)

        duckiebot_ip = get_duckiebot_ip(duckiebot_name)
        if parsed.local:
            duckiebot_client = check_docker_environment()
        else:
            duckiebot_client = docker.DockerClient("tcp://" + duckiebot_ip + ":2375")

        container_name = "demo_%s" % parsed.demo_name
        remove_if_running(duckiebot_client, container_name)
        image_base = parsed.image_to_run
        env_vars = default_env(duckiebot_name, duckiebot_ip)
        env_vars.update({
            "VEHICLE_NAME": duckiebot_name,
            "VEHICLE_IP": duckiebot_ip
        })

        # get robot_type
        if parsed.robot_type == 'auto':
            # retrieve robot type from device
            dtslogger.info(f'Waiting for device "{duckiebot_name}"...')
            hostname = duckiebot_name.replace('.local', '')
            _, _, data = wait_for_service('DT::ROBOT_TYPE', hostname)
            parsed.robot_type = data['type']
            dtslogger.info(f'Detected device type is "{parsed.robot_type}".')
        else:
            dtslogger.info(f'Device type forced to "{parsed.robot_type}".')

        # get robot_configuration
        if parsed.robot_configuration == 'auto':
            # retrieve robot configuration from device
            dtslogger.info(f'Waiting for device "{duckiebot_name}"...')
            hostname = duckiebot_name.replace('.local', '')
            _, _, data = wait_for_service('DT::ROBOT_CONFIGURATION', hostname)
            parsed.robot_configuration = data['configuration']
            dtslogger.info(f'Detected device configuration is "{parsed.robot_configuration}".')
        else:
            dtslogger.info(f'Device configuration forced to "{parsed.robot_configuration}".')

        if parsed.demo_name == "base":
            cmd = "/bin/bash"
        else:
            if parsed.package_name:
                cmd = "roslaunch %s %s.launch veh:=%s robot_type:=%s robot_configuration:=%s" % (
                    parsed.package_name,
                    parsed.demo_name,
                    duckiebot_name,
                    parsed.robot_type,
                    parsed.robot_configuration
                )
                dtslogger.warning('You are using the option --package_name (-p) to run the demo. '
                                  'This is obsolete. Please, provide a launcher name instead.')
            else:
                cmd = f'dt-launcher-{parsed.demo_name}'

        pull_if_not_exist(duckiebot_client, image_base)

        dtslogger.info("Running command %s" % cmd)
        duckiebot_client.containers.run(
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

        if parsed.demo_name == "base" or parsed.debug:
            attach_cmd = "docker -H %s.local attach %s" % (
                duckiebot_name,
                container_name,
            )
            start_command_in_subprocess(attach_cmd)
