import os
import re
import socket

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
