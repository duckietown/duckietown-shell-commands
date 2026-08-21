import os
import platform
import re
import socket
import subprocess

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
    local_virtual_robot_ip = get_local_virtual_robot_ip(duckiebot_name)
    if local_virtual_robot_ip is not None:
        return local_virtual_robot_ip

    try:
        duckiebot_ip = get_ip_from_ping("%s.local" % duckiebot_name)
    except Exception as e:
        print(e)
        duckiebot_ip = get_ip_from_ping(duckiebot_name)

    return duckiebot_ip


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


def get_local_virtual_robot_ip(robot: str):
    robot_name = robot.removesuffix(".local")
    container_name = f"dts-virtual-{robot_name}"
    try:
        client = docker.from_env()
        containers = client.containers
        container = containers.get(container_name)
        if container.status != "running":
            return None
        attributes = container.attrs
        network_settings = attributes.get("NetworkSettings", {})
        networks = network_settings.get("Networks", {})
        network_values = networks.values()
        for network in network_values:
            ip_address = network.get("IPAddress")
            if ip_address:
                return ip_address
    except (docker.errors.NotFound, docker.errors.DockerException):
        return None
    return None


def is_local_virtual_robot_running(robot: str) -> bool:
    robot_name = robot.removesuffix(".local")
    container_name = f"dts-virtual-{robot_name}"
    try:
        client = docker.from_env()
        containers = client.containers
        container = containers.get(container_name)
        return container.status == "running"
    except (docker.errors.NotFound, docker.errors.DockerException):
        return False


def best_host_for_robot(robot: str, allow_static: bool = True) -> str:
    robot_name = robot[:-6] if robot.endswith(".local") else robot
    local_virtual_robot_ip = get_local_virtual_robot_ip(robot_name)
    if local_virtual_robot_ip is not None:
        dtslogger.debug(
            f"Best host for robot '{robot}' is Docker-network address '{local_virtual_robot_ip}' "
            "because it is a locally running virtual robot"
        )
        return local_virtual_robot_ip
    mdns: str = f"{robot_name}.local" if not robot.endswith(".local") else robot
    # try to get the IP address first (this is a static option)
    if allow_static:
        try:
            ip = socket.gethostbyname(mdns)
            # ---
            dtslogger.debug(f"Best host for robot '{robot}' is its IP address '{ip}' (static)")
            return ip
        except socket.gaierror:
            dtslogger.debug(f"Failed to resolve IP address from mDNS name '{mdns}'.")
    # ---
    dtslogger.debug(f"Best host for robot '{robot}' is its local mDNS name '{mdns}'")
    return mdns
