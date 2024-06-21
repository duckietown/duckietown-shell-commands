import os
import platform
import re
import socket
import subprocess
from functools import lru_cache

from dt_shell import dtslogger
from utils.exceptions import NetworkingError


def get_ip_from_ping(alias):
    response = os.popen("ping -c 1 %s" % alias).read()
    m = re.search("PING.*?\((.*?)\)+", response)
    if m:
        return m.group(1)
    else:
        raise Exception("Unable to locate %s!" % alias)


def get_duckiebot_ip(duckiebot_name):
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
    return os.popen(f'ip addr show {ifname}' + ' | grep "\<inet\>" | awk \'{ print $2 }\' '
                                               '| awk -F "/" \'{ print $1 }\'').read().strip()


@lru_cache
def best_host_for_robot(robot: str, allow_static: bool = True) -> str:
    mdns: str = f"{robot}.local" if not robot.endswith(".local") else robot
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
