"""Common utility functions for Tailscale commands."""

import json
import os
import re
import ssl
import urllib.request
from urllib.error import HTTPError
from urllib.request import Request
from ssl import SSLError

try:
    import certifi
    HAS_CERTIFI = True
except ImportError:
    HAS_CERTIFI = False

from docker import DockerClient
from dt_shell import dtslogger

from utils.docker_utils import DEFAULT_MACHINE, sanitize_docker_baseurl
from utils.resolve import get_duckiebot_host


def get_tailscale_api_key() -> str | None:
    """Get Tailscale API key from environment variables.
    
    Returns:
        API key if found, None otherwise
    """
    api_key = os.environ.get("TAILSCALE_API_KEY")
    if api_key:
        return api_key
    api_key = os.environ.get("TS_API_KEY")
    if api_key:
        return api_key
    return None


def delete_tailscale_device(device_id: str, api_key: str) -> bool:
    """Delete a device from the Tailscale network via API.
    
    Args:
        device_id: The Tailscale device/node ID
        api_key: Tailscale API key with devices:write permission
        
    Returns:
        True if deletion succeeded, False otherwise
    """
    try:
        url = f"https://api.tailscale.com/api/v2/device/{device_id}"
        req = Request(url, method="DELETE")
        req.add_header("Authorization", f"Bearer {api_key}")
        # Create SSL context with certifi certificates if available
        cafile = certifi.where() if HAS_CERTIFI else None
        ssl_context = ssl.create_default_context(cafile=cafile)
        with (
            urllib.request.urlopen(req, timeout=10, context=ssl_context) 
            as response
        ):
            if response.status in (200, 204):
                return True
            dtslogger.warning(
                f"Unexpected response status: {response.status}"
            )
            return False
    except HTTPError as error:
        error_data = error.read()
        error_msg = (
            error_data.decode() if hasattr(error, "read") else str(error)
        )
        if error.code == 401:
            dtslogger.error(
                "API key is invalid or expired. Ensure TAILSCALE_API_KEY "
                "has 'devices:write' permission."
            )
        elif error.code == 403:
            dtslogger.error(
                "Permission denied. The API key may lack 'devices:write' "
                "permission or access to this tailnet."
            )
        elif error.code == 404:
            dtslogger.debug("Device not found (may already be deleted)")
            return True  # Consider it success if already gone
        else:
            dtslogger.warning(
                f"HTTP {error.code} error deleting device: {error.reason}"
            )
        dtslogger.debug(f"API error details: {error_msg}")
        return False
    except SSLError as error:
        dtslogger.error(
            f"SSL certificate verification failed: {error}. "
            "You may need to install Python certificates. "
            r"On macOS, run: /Applications/Python\ */Install\ "
            "Certificates.command"
        )
        return False
    except Exception as error:
        dtslogger.warning(f"Error deleting device: {error}")
        return False


def find_devices_by_hostname(hostname: str, api_key: str) -> list[dict]:
    """Find devices in the Tailscale network matching a hostname pattern.
    
    Args:
        hostname: The base hostname to search for (e.g., "entebot208")
        api_key: Tailscale API key with devices:read permission
        
    Returns:
        List of matching devices with keys: hostname, node_id, ip, online
    """
    try:
        url = "https://api.tailscale.com/api/v2/tailnet/-/devices"
        req = Request(url)
        req.add_header("Authorization", f"Bearer {api_key}")
        cafile = certifi.where() if HAS_CERTIFI else None
        ssl_context = ssl.create_default_context(cafile=cafile)
        with (
            urllib.request.urlopen(req, timeout=10, context=ssl_context) 
            as response
        ):
            if response.status != 200:
                return []
            response_data = response.read()
            decoded_response_data = response_data.decode()
            data = json.loads(decoded_response_data)
            devices = data.get("devices", [])
            # Find devices matching the hostname pattern
            matching_devices = []
            base_hostname = re.sub(r"-\d+$", "", hostname)
            escaped_base = re.escape(base_hostname)
            for device in devices:
                device_hostname = device.get("hostname", "")
                # Match exact base or base-N pattern
                if (
                    device_hostname == base_hostname
                    or re.match(rf"^{escaped_base}-\d+$", device_hostname)
                ):
                    addresses = device.get("addresses", [])
                    matching_devices.append({
                        "hostname": device_hostname,
                        "node_id": device.get("nodeId", device.get("id", "")),
                        "ip": addresses[0] if addresses else "",
                        "online": not device.get("offline", False),
                    })
            return matching_devices
    except HTTPError as error:
        if error.code in (401, 403):
            dtslogger.debug(
                "API authentication failed. Skipping duplicate check."
            )
        return []
    except Exception:
        return []


def resolve_and_connect_docker(machine: str) -> DockerClient | None:
    """
    Resolve hostname and connect to Docker endpoint.
    
    Args:
        machine: Machine hostname or DEFAULT_MACHINE
        
    Returns:
        DockerClient instance if successful, None otherwise
    """
    # Resolve hostname if needed
    if (
        machine
        and machine != DEFAULT_MACHINE
        and ":" not in machine
        and "://" not in machine
    ):
        machine = get_duckiebot_host(machine)
    # Connect to Docker endpoint
    docker_host = sanitize_docker_baseurl(machine)
    dtslogger.info(
        f"Connecting to Docker endpoint '{docker_host or 'local'}'..."
    )
    try:
        client = DockerClient(base_url=docker_host)
        client.ping()
        return client
    except Exception as error:
        dtslogger.error(f"Failed to connect to Docker endpoint: {error}")
        return None


def log_api_key_info(command: str) -> None:
    """Log information about Tailscale API keys.
    
    Args:
        command: The command name for context
    """
    dtslogger.warning("No Tailscale API key found.")
    dtslogger.info(
        f"To automatically delete old devices on {command}, set the "
        "TAILSCALE_API_KEY (or TS_API_KEY) environment variable."
    )
    dtslogger.info(
        "To create an API key, navigate to "
        "https://login.tailscale.com/admin/settings/keys."
    )
    log_old_devices_info()

def log_old_devices_info() -> None:
    """Log information about manually removing old devices."""
    dtslogger.info(
        "To manually remove old devices, navigate to "
        "https://login.tailscale.com/admin/machines."
    )