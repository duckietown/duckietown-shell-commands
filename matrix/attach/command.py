import argparse
import os
import platform
import re
import subprocess

import requests
from dt_shell import DTCommandAbs, dtslogger, DTShell

from utils.misc_utils import sanitize_hostname

DUCKIEMATRIX_ROS_API_URL = "http://{robot_hostname}/ros/duckiematrix/connect?" \
                           "data_in={data_in_uri}&data_out={data_out_uri}"
DATA_IN_PROTOCOL = "tcp"
DATA_OUT_PROTOCOL = "tcp"
DATA_IN_PORT = 7505
DATA_OUT_PORT = 7506


class DTCommand(DTCommandAbs):

    help = f'Attaches a world robot to an existing Duckiematrix network'

    @staticmethod
    def _parse_args(args):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-e",
            "--engine",
            dest="engine_hostname",
            default=None,
            type=str,
            help="Hostname or IP address of the engine to attach the robot to"
        )
        parser.add_argument("robot", nargs=1, help="Name of the robot to attach to the Matrix")
        parsed, _ = parser.parse_known_args(args=args)
        return parsed

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = kwargs.get("parsed", None)
        if parsed is None:
            parsed = DTCommand._parse_args(args)
        # ---
        parsed.robot = parsed.robot[0]
        # get IP address on the gateway network interface
        if parsed.engine_hostname is None:
            dtslogger.info("Engine hostname not given, assuming the engine is running "
                           "on the local machine.")
            _, default_interface = get_default_gateway_and_interface()
            if default_interface is None:
                dtslogger.warning("An error occurred while figuring out the gateway interface.\n"
                                  f"Will assume that the robots can reach the engine at the "
                                  f"hostname 'localhost'.")
                engine_hostname = "localhost"
            else:
                dtslogger.info(f"Found gateway interface: {default_interface}")
                dtslogger.info("Figuring out the IP address...")
                engine_hostname = get_ip_address(default_interface)
                dtslogger.info(f"IP address found: {engine_hostname}")
        # compile data_in and data_out URIs
        data_in_uri = f"{DATA_IN_PROTOCOL}://{engine_hostname}:{DATA_IN_PORT}"
        data_out_uri = f"{DATA_OUT_PROTOCOL}://{engine_hostname}:{DATA_OUT_PORT}"
        # compile robot's API URI
        robot_api_uri = DUCKIEMATRIX_ROS_API_URL.format(
            robot_hostname=sanitize_hostname(parsed.robot),
            data_in_uri=data_in_uri,
            data_out_uri=data_out_uri,
        )
        dtslogger.debug(f"GET: {robot_api_uri}")
        # ask the world robot to join the network
        try:
            dtslogger.info(f"Requesting robot {parsed.robot} to join Duckiematrix engine at "
                           f"{engine_hostname}...")
            requests.get(robot_api_uri).json()
            dtslogger.info("Request sent, robot should now connect.")
        except BaseException as e:
            dtslogger.error("An error occurred while contacting the robot.\n"
                            f"The error reads:\n{e}")
            return

    @staticmethod
    def complete(shell, word, line):
        return []


def get_default_gateway_and_interface():
    if platform.system() == "Darwin":
        route_default_result = subprocess.check_output(["route", "get", "default"])
        route_default_result = route_default_result.decode("utf-8")
        gateway = re.search(r"\d{1,3}.\d{1,3}.\d{1,3}.\d{1,3}", route_default_result).group(0)
        default_interface = re.search(r"(?:interface:.)(.*)", route_default_result).group(1)

    elif platform.system() == "Linux":
        route_default_result = subprocess.check_output(["ip", "route"])
        route_default_result = route_default_result.decode("utf-8")
        route_default_result = re.findall(r"([\w.][\w.]*'?\w?)", route_default_result)
        gateway = route_default_result[2]
        default_interface = route_default_result[4]

    else:
        print("(x) Could not read default routes.")
        return None, None

    if route_default_result:
        return gateway, default_interface


def get_ip_address(ifname):
    return os.popen(f'ip addr show {ifname}' + ' | grep "\<inet\>" | awk \'{ print $2 }\' '
                                               '| awk -F "/" \'{ print $1 }\'').read().strip()
