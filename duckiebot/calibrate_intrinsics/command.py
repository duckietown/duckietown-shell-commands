from __future__ import print_function

import argparse
import platform
import subprocess
import os
import socket

from dt_shell import DTCommandAbs, dtslogger
from dt_shell.env_checks import check_docker_environment
from utils.networking_utils import get_duckiebot_ip
from utils.docker_utils import get_remote_client, remove_if_running


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):

        prog = 'dts duckiebot calibrate_intrinsics DUCKIEBOT_NAME'
        usage = """
Calibrate: 

    %(prog)s
"""

        parser = argparse.ArgumentParser(prog=prog, usage=usage)
        parser.add_argument('hostname', default=None, help='Name of the Duckiebot to calibrate')
        parser.add_argument('--base_image', dest='image',
                            default="duckietown/rpi-duckiebot-base:master19-no-arm")

        parsed_args = parser.parse_args(args)
        hostname = parsed_args.hostname
        duckiebot_ip = get_duckiebot_ip(hostname)
        duckiebot_client = get_remote_client(duckiebot_ip)

        # is the interface running?
        try:
            duckiebot_containers = duckiebot_client.containers.list()
            interface_container_found = False
            for c in duckiebot_containers:
                if 'duckiebot-interface' in c.name:
                    interface_container_found = True
            if not interface_container_found:
                dtslogger.error("The  duckiebot-interface is not running on the duckiebot")
                exit()
        except Exception as e:
            dtslogger.warn(
                "Not sure if the duckiebot-interface is running because we got and exception when trying: %s" % e)

        # is the raw imagery being published?
        try:
            duckiebot_containers = duckiebot_client.containers.list()
            raw_imagery_found = False
            for c in duckiebot_containers:
                if 'demo_camera' in c.name:
                    raw_imagery_found = True
            if not raw_imagery_found:
                dtslogger.error("The  demo_camera is not running on the duckiebot - please run `dts duckiebot demo --demo_name camera --duckiebot_name %s" % hostname)
                exit()

        except Exception as e:
            dtslogger.warn("%s" % e)


        image = parsed_args.image


        client = check_docker_environment()
        container_name = "intrisic_calibration_%s" % hostname
        remove_if_running(client,container_name)
        env = {'HOSTNAME': hostname,
               'ROS_MASTER': hostname,
               'DUCKIEBOT_NAME': hostname,
               'ROS_MASTER_URI': 'http://%s:11311' % duckiebot_ip,
               'QT_X11_NO_MITSHM': 1}

        volumes = {}
        subprocess.call(["xhost", "+"])

        p = platform.system().lower()
        if 'darwin' in p:
            env['DISPLAY'] = '%s:0' % socket.gethostbyname(socket.gethostname())
            volumes = {
                '/tmp/.X11-unix': {'bind': '/tmp/.X11-unix', 'mode': 'rw'}
            }
        else:
            env['DISPLAY'] = os.environ['DISPLAY']

        dtslogger.info("Running %s on localhost with environment vars: %s" %
                       (container_name, env))

        dtslogger.info("When the window opens you will need to move the checkerboard around in front of the Duckiebot camera")
        cmd = "roslaunch duckietown intrinsic_calibration.launch veh:=%s" % hostname

        params = {'image': image,
                  'name': container_name,
                  'network_mode': 'host',
                  'environment': env,
                  'privileged': True,
                  'stdin_open': True,
                  'tty': True,
                  'detach': True,
                  'command': cmd,
                  'volumes': volumes
                  }

        container = client.containers.run(**params)