from __future__ import annotations
import os
import socket
import subprocess
from typing import Iterable, Optional

from utils.networking_utils import get_local_virtual_robot_ip


def _is_reachable(host: str, port: int = 22, timeout: float = 1.5) -> bool:
    """Fast check: try TCP connect; if blocked, fall back to getaddrinfo + ping."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        # DNS ok but SSH closed? Still verify host resolves and responds to ping.
        try:
            socket.getaddrinfo(host, None)
        except socket.gaierror:
            return False
        try:
            # -c 1 one packet, -W timeout seconds (Linux/BusyBox compatible)
            subprocess.run(
                ["ping", "-c", "1", "-W", str(timeout), host],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
            )
            return True
        except Exception:
            return False


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
      2) Docker-network address if local virtual robot
      3) `duckiebot_name`.local (mDNS)
      4) `duckiebot_name` (MagicDNS short name)
      5) `duckiebot_name`.<TAILNET_DOMAIN> (MagicDNS FQDN, optional)
      6) any extra candidates passed in
    Raises RuntimeError if none are reachable.
    """
    override = os.environ.get("DUCKIEBOT_HOST")
    if override:
        return override

    local_virtual_robot_ip = get_local_virtual_robot_ip(duckiebot_name)
    if local_virtual_robot_ip is not None:
        return local_virtual_robot_ip

    candidates = [f"{duckiebot_name}.local", duckiebot_name]
    candidates += list(_magicdns_candidates(duckiebot_name))
    if extra_candidates:
        candidates += list(extra_candidates)

    tried = []
    for host in candidates:
        if _is_reachable(host):
            return host
        tried.append(host)

    raise RuntimeError(
        f"Could not reach Duckiebot via any hostname. Tried: {', '.join(tried)}.\n"
        "Tip: export DUCKIEBOT_HOST=<ip-or-host>, or set TAILNET_DOMAIN=tailnet-xyz.ts.net."
    )


def resolve_robot_host(robot_name: str) -> str:
    """Resolve a robot name to its best reachable host.
    
    Handles .local suffix stripping and passes the original name as an extra
    candidate so get_duckiebot_host can fall back to it if needed.
    """
    stripped = robot_name[:-6] if robot_name.endswith(".local") else robot_name
    return get_duckiebot_host(stripped, extra_candidates=[robot_name])
