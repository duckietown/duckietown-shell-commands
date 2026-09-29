import os
import platform
import re
import socket
import subprocess
from functools import lru_cache

import docker

from dt_shell import dtslogger
from utils.exceptions import NetworkingError


def get_ip_from_ping(alias):
    response = os.popen("ping -c 1 %s" % alias).read()
    m = re.search(r"PING.*?\((.*?)\)+", response)
    if m:
        return m.group(1)
    else:
        raise Exception("Unable to locate %s!" % alias)


def get_duckiebot_ip(duckiebot_name):
    host = best_host_for_robot(duckiebot_name)
    return socket.gethostbyname(host)


def resolve_hostname(hostname: str) -> str:
    # separate protocol (if any)
    protocol = ""
    if "://" in hostname:
        idx = hostname.index("://")
        protocol, hostname = hostname[0 : idx + len("://")], hostname[idx + len("://") :]
    # separate port (if any)
    port = ""
    if ":" in hostname:
        idx = hostname.index(":")
        hostname, port = hostname[0:idx], hostname[idx:]
    # perform name resolution
    try:
        ip = socket.gethostbyname(hostname)
    except socket.gaierror as e:
        msg = f"Failed to resolve host using name '{hostname}'.\n\tException(socket.gaierror): {e}"
        raise NetworkingError(msg)
    return protocol + ip + port


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
    # ---
    if route_default_result:
        return gateway, default_interface


def get_interface_ip_address(ifname):
    out = subprocess.check_output(['ip', '-4', 'addr', 'show', ifname], text=True)
    m = re.search(r'\binet\s+(\d+\.\d+\.\d+\.\d+)/', out)
    return m.group(1) if m else None


def is_local_virtual_robot_running(robot: str) -> bool:
    container_name = f"dts-virtual-{robot}"
    try:
        client = docker.from_env()
        container = client.containers.get(container_name)
        return container.status == "running"
    except (docker.errors.NotFound, docker.errors.DockerException):
        return False


@lru_cache
def best_host_for_robot(robot: str, allow_static: bool = True) -> str:
    robot_name = robot[:-6] if robot.endswith(".local") else robot
    if "." not in robot and is_local_virtual_robot_running(robot):
        dtslogger.debug(
            f"Best host for robot '{robot}' is loopback because it is a locally running virtual robot"
        )
        return "127.0.0.1"
    if robot.endswith(".local"):
        hostnames = [robot, robot_name]
    elif "." in robot:
        hostnames = [robot]
    else:
        hostnames = [f"{robot}.local", robot]
    if allow_static:
        for hostname in hostnames:
            try:
                ip = socket.gethostbyname(hostname)
            except socket.gaierror:
                dtslogger.debug(f"Failed to resolve IP address from hostname '{hostname}'.")
                continue
            dtslogger.debug(f"Best host for robot '{robot}' is its IP address '{ip}' (static)")
            return ip
    dtslogger.debug(f"Best host for robot '{robot}' is its hostname '{hostnames[0]}'")
    return hostnames[0]
