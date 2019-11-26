import argparse
import os
import platform
import socket
import subprocess

import docker
from dt_shell import DTCommandAbs, DTShell, dtslogger
from dt_shell.env_checks import check_docker_environment
from utils.cli_utils import start_command_in_subprocess
from utils.docker_utils import remove_if_running, pull_if_not_exist
from utils.networking_utils import get_duckiebot_ip


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts duckiebot keyboard_control DUCKIEBOT_NAME"
        usage = """
Keyboard control:

    %(prog)s
"""

        parser = argparse.ArgumentParser(prog=prog, usage=usage)

        parser.add_argument('hostname', default=None, help='Name of the Duckiebot to calibrate')
        parser.add_argument('--cli', dest='cli', default=False, action='store_true',
                            help='A flag, if set will run with CLI instead of with GUI')
        parser.add_argument('--network', default='host', help='Name of the network which to connect')
        parser.add_argument('--sim', action='store_true', default=False,
                            help='are we running in simulator?')
        parser.add_argument('--base_image', dest='image',
                            default="duckietown/dt-core:daffy-amd64",
                            help="The base image, probably don't change the default")

        parsed_args = parser.parse_args(args)

        if parsed_args.sim:
            duckiebot_ip = "sim"
        else:
            duckiebot_ip = get_duckiebot_ip(duckiebot_name=parsed_args.hostname)

        network_mode = parsed_args.network

        if not parsed_args.cli:
            run_gui_controller(parsed_args.hostname, parsed_args.image, duckiebot_ip, network_mode)
        else:
            run_cli_controller(parsed_args.hostname, parsed_args.image, duckiebot_ip, network_mode, parsed_args.sim)


def run_gui_controller(hostname, image, duckiebot_ip, network_mode):
    client = check_docker_environment()
    container_name = "joystick_gui_%s" % hostname
    remove_if_running(client, container_name)

    env = { 'HOSTNAME':hostname,
            'ROS_MASTER': hostname,
           'VEHICLE_NAME': hostname,
           'ROS_MASTER_URI': 'http://%s:11311' % duckiebot_ip}

    env["QT_X11_NO_MITSHM"] = 1

    volumes = {"/tmp/.X11-unix": {"bind": "/tmp/.X11-unix", "mode": "rw"}}

    subprocess.call(["xhost", "+"])

    p = platform.system().lower()
    if "darwin" in p:
        dtslogger.warn(
            "We can try but running the joystick gui on MacOSx is not expected to work..."
        )
        env["DISPLAY"] = "%s:0" % socket.gethostbyname(socket.gethostname())
    else:
        env["DISPLAY"] = os.environ["DISPLAY"]

    dtslogger.info(
        "Running %s on localhost with environment vars: %s" % (container_name, env)
    )

    if "master19" in image:
        image = "duckietown/rpi-duckiebot-base:master19-no-arm"
        cmd = "python misc/virtualJoy/virtualJoy.py %s" % hostname
    elif 'daffy' in image:
        image = "duckietown/dt-core:daffy-amd64"
        cmd = "roslaunch virtual_joystick virtual_joystick_gui.launch veh:=%s" % hostname

    else:
        msg = f"Not sure what to do with {image!r}"
        raise Exception(msg)

        
    params = {'image': image,
              'name': container_name,
              'network_mode': network_mode,
              'environment': env,
              'privileged': True,
              'stdin_open': True,
              'tty': True,
              'command': cmd,
              'detach': True,
              'volumes': volumes
              }


    pull_if_not_exist(client, params['image'])
    container = client.containers.run(**params)
    cmd = "docker attach %s" % container_name
    start_command_in_subprocess(cmd)


### if it's the CLI may as well run it on the robot itself.
def run_cli_controller(hostname,image,duckiebot_ip, network_mode, sim):
    if sim:
        duckiebot_client = check_docker_environment()
    else:
        duckiebot_client = docker.DockerClient('tcp://' + duckiebot_ip + ':2375')
    container_name = "joystick_cli_%s" % hostname
    remove_if_running(duckiebot_client, container_name)
    env = { 'HOSTNAME':hostname,
            'ROS_MASTER':hostname,
            'VEHICLE_NAME':hostname,
            'ROS_MASTER_URI':'http://%s:11311' % duckiebot_ip}

    dtslogger.info("Running %s on localhost with environment vars: %s" %
                   (container_name, env))


    if 'master19' in image:
        image = "duckietown/rpi-duckiebot-base:master19" # run on robot
        cmd = "python misc/virtualJoy/joy_cli.py %s" % hostname
    elif 'daffy' in image:
        if sim:
            image = "duckietown/dt-core:daffy-amd64"
        else:
            image = "duckietown/dt-core:daffy"
        cmd = "roslaunch virtual_joystick virtual_joystick_cli.launch veh:=%s" % hostname

    else:
        msg = f"Not sure what to use for {image}"
        raise Exception(msg)

        
    params = {'image': image,
                'name': container_name,
                'network_mode': network_mode,
                'environment': env,
                'privileged': True,
                'stdin_open': True,
                'tty':True,
                'command': cmd,
              'detach':True
              }

    pull_if_not_exist(duckiebot_client, params['image'])
    container = duckiebot_client.containers.run(**params)

    if sim:
        cmd = 'docker attach %s' % container_name
    else:
        cmd = 'docker -H %s.local attach %s' % (hostname, container_name)
    start_command_in_subprocess(cmd)
