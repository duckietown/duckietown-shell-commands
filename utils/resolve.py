from __future__ import annotations
import os
import socket
from typing import Iterable, Optional

from utils.networking_utils import is_local_virtual_robot_running


def _resolves(host: str) -> bool:
    try:
        socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    return True


def _magicdns_candidates(bot_name: str) -> Iterable[str]:
    # Optional: if a user exports TAILNET_DOMAIN=tailnet-xyz.ts.net we’ll try FQDN too
    tailnet = os.environ.get("TAILNET_DOMAIN", "").strip()
    if tailnet:
        yield f"{bot_name}.{tailnet}"


def get_duckiebot_host(
    duckiebot_name: str = "duckiebot",
    extra_candidates: Optional[Iterable[str]] = None,
) -> str:
    """Return the best hostname to reach the Duckiebot.
    Precedence:
      1) DUCKIEBOT_HOST (explicit override)
      2) loopback if local virtual robot
      3) `duckiebot_name`.local (mDNS)
      4) `duckiebot_name` (MagicDNS short name)
      5) `duckiebot_name`.<TAILNET_DOMAIN> (MagicDNS FQDN, optional)
      6) any extra candidates passed in
    Raises RuntimeError if none resolve.
    """
    override = os.environ.get("DUCKIEBOT_HOST")
    if override:
        return override

    if "." not in duckiebot_name and is_local_virtual_robot_running(duckiebot_name):
        return "127.0.0.1"

    robot_name = duckiebot_name[:-6] if duckiebot_name.endswith(".local") else duckiebot_name
    if duckiebot_name.endswith(".local"):
        candidates = [duckiebot_name, robot_name]
    elif "." in duckiebot_name:
        candidates = [duckiebot_name]
    else:
        candidates = [f"{robot_name}.local", robot_name]
    if "." not in robot_name:
        candidates += list(_magicdns_candidates(robot_name))
    if extra_candidates:
        candidates += list(extra_candidates)

    tried = []
    for host in candidates:
        if _resolves(host):
            return host
        tried.append(host)

    raise RuntimeError(
        f"Could not resolve Duckiebot via any hostname. Tried: {', '.join(tried)}.\n"
        "Tip: export DUCKIEBOT_HOST=<ip-or-host>, or set TAILNET_DOMAIN=tailnet-xyz.ts.net."
    )


def resolve_robot_host(robot_name: str) -> str:
    """Resolve a robot name without losing an explicitly supplied hostname."""
    return get_duckiebot_host(robot_name)
