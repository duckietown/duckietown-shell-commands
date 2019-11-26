import argparse
import os
import platform
import subprocess

from dt_shell import DTCommandAbs, DTShell, dtslogger
from dt_shell.env_checks import check_docker_environment
from utils.cli_utils import start_command_in_subprocess
from utils.docker_utils import remove_if_running
from utils.networking_utils import get_duckiebot_ip


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts start_gui_tools DUCKIEBOT_NAME"
        usage = """
Keyboard control: 

    %(prog)s
"""

        parser = argparse.ArgumentParser(prog=prog, usage=usage)
        parser.add_argument(
            "hostname", default=None, help="Name of the Duckiebot"
        )
        parser.add_argument(
            "--network", default="host", help="Name of the network which to connect"
        )
        parser.add_argument(
            "--sim",
            action="store_true",
            default=False,
            help="are we running in simulator?",
        )
        parser.add_argument(
            "--base_image",
            dest="image",
            default="duckietown/dt-core:daffy-amd64",
            help="The base image, probably don't change the default",
        )
        parser.add_argument(
            "--novnc",
            action="store_true",
            default=True,
            help="should we run the novnc server",
        )
            
        parsed_args = parser.parse_args(args)

        if parsed_args.sim:
            duckiebot_ip = "localhost"
        else:
            duckiebot_ip = get_duckiebot_ip(duckiebot_name=parsed_args.hostname)

        hostname = parsed_args.hostname
        image = parsed_args.image

        client = check_docker_environment()
        container_name = "interactive_gui_tools_%s" % hostname
        remove_if_running(client, container_name)

        if parsed_args.sim:
            env = {
                "HOSTNAME": "default",
                "ROS_MASTER": hostname,
                "DUCKIEBOT_NAME": hostname,
                "ROS_MASTER_URI": "http://%s:11311" % hostname,
            }
        else:
            env = {
                "HOSTNAME": hostname,
                "ROS_MASTER": hostname,
                "DUCKIEBOT_NAME": hostname,
                "ROS_MASTER_URI": "http://%s:11311" % duckiebot_ip,
            }

        env["QT_X11_NO_MITSHM"] = 1

        p = platform.system().lower()
        volumes = {
            '/tmp/.X11-unix': {'bind': '/tmp/.X11-unix', 'mode': 'rw'}
        }
        
        if 'darwin' in p:
            subprocess.call(["xhost", "+", '127.0.0.1'])
            env['DISPLAY'] = 'host.docker.internal:0'
        else:
            subprocess.call(["xhost", "+"])
            env["DISPLAY"] = os.environ["DISPLAY"]

        dtslogger.info(
            "Running %s on localhost with environment vars: %s" % (container_name, env)
        )

        cmd = "/bin/bash"

        params = {
            "image": image,
            "name": container_name,
            "network_mode": parsed_args.network,
            "environment": env,
            "privileged": True,
            "stdin_open": True,
            "tty": True,
            "detach": True,
            "command": cmd,
            "volumes": volumes,
        }
        
        container = client.containers.run(**params)


        
        if parsed_args.novnc:
            novnc_container_name = "novnc_%s" % hostname
            remove_if_running(client, novnc_container_name)
            vncenv = env
            vncenv['VEHICLE_NAME'] = env['HOSTNAME']
            vncparams = {
                "image": "duckietown/docker-ros-vnc:daffy",
                "name": novnc_container_name,
                "network_mode": parsed_args.network,
                "environment": vncenv,
                "ports": {'5901/tcp': 5901, '6901/tcp': 6901},
                "detach": True,
                "privileged": True,
                }
            dtslogger.info(
                "Running novnc. To use navigate your browser http://localhost:6901/vnc.html. Password is quackquack."
                )
            novnc_container = client.containers.run(**vncparams)
            

        
        attach_cmd = "docker attach %s" % container_name
        start_command_in_subprocess(attach_cmd)
