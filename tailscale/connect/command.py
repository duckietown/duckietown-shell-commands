import json
import re
import subprocess
import time
import webbrowser
from argparse import ArgumentParser
from subprocess import TimeoutExpired
from urllib.parse import urlparse

from docker import DockerClient
from docker.errors import APIError, NotFound
from docker.models.containers import Container
from dt_shell import DTCommandAbs, DTShell, dtslogger

from utils.docker_utils import DEFAULT_MACHINE
from utils.tailscale_utils import (
    delete_tailscale_device,
    find_devices_by_hostname,
    get_tailscale_api_key,
    log_api_key_info,
    log_old_devices_info,
    resolve_and_connect_docker,
)


class DTCommand(DTCommandAbs):
    help = "Connects to a Tailscale network"

    @staticmethod
    def _configure_host_magicdns(
        container: Container,
        machine: str
    ) -> bool:
        """Configure host DNS to use Tailscale MagicDNS.
        
        This configures /etc/resolv.conf to:
        1. Use 100.100.100.100 (Tailscale DNS) as primary nameserver
        2. Add the Tailscale domain to the search path
        3. Keep the original nameserver as fallback
        
        Returns True if successful, False otherwise.
        """
        if machine != DEFAULT_MACHINE:
            dtslogger.debug(
                "Skipping host DNS configuration for remote machine."
            )
            return False
        try:
            # Get MagicDNS suffix from Tailscale status
            status_check = container.exec_run(
                "tailscale status --json",
                detach=False
            )
            if status_check.exit_code != 0 or not status_check.output:
                return False
            decoded_output = status_check.output.decode()
            status_data = json.loads(decoded_output)
            magic_dns_suffix = status_data.get("MagicDNSSuffix", "")
            current_tailnet = status_data.get("CurrentTailnet", {})
            magic_dns_enabled = current_tailnet.get("MagicDNSEnabled", False)
            if not magic_dns_enabled or not magic_dns_suffix:
                dtslogger.debug(
                    "MagicDNS is not enabled, skipping host DNS configuration."
                )
                return False
            # Read current resolv.conf to get the original nameserver
            try:
                with open("/etc/resolv.conf", "r") as file:
                    original_content = file.read()
            except Exception as error:
                dtslogger.debug(f"Could not read /etc/resolv.conf: {error}")
                return False
            # Check if DNS is already properly configured
            has_tailscale_dns = (
                "nameserver 100.100.100.100" in original_content
            )
            has_search_domain = (
                f"search {magic_dns_suffix}" in original_content
            )
            if has_tailscale_dns and has_search_domain:
                dtslogger.debug(
                    "Host DNS is already configured for MagicDNS, skipping."
                )
                return True
            # Extract original nameserver
            original_nameserver = None
            for line in original_content.split("\n"):
                if (
                    line.startswith("nameserver")
                    and "100.100.100.100" not in line
                ):
                    split_line = line.split()
                    original_nameserver = (
                        split_line[1] if len(split_line) > 1 else None
                    )
                    break
            if not original_nameserver:
                original_nameserver = "8.8.8.8"  # Fallback to Google DNS
            # Ask user for permission to modify DNS
            dtslogger.info(
                "MagicDNS is enabled. You can configure the host to use "
                "Tailscale DNS for short hostname resolution."
            )
            print(
                "\nProposed DNS configuration:\n"
                "  - Primary DNS: 100.100.100.100 (Tailscale)\n"
                f"  - Search domain: {magic_dns_suffix}\n"
                f"  - Fallback DNS: {original_nameserver}\n"
                "This allows you to use short hostnames like "
                "'ping <hostname>'.\n"
            )
            choice = input("Configure host DNS for MagicDNS? [Y/n]: ")
            if choice.lower() == "n":
                dtslogger.info("Skipped DNS configuration.")
                return False
            # Create new resolv.conf content
            new_content = (
                "nameserver 100.100.100.100\n"
                f"search {magic_dns_suffix}\n"
                f"nameserver {original_nameserver}\n"
            )
            # Write new configuration using sudo tee
            try:
                encoded_content = new_content.encode()
                process = subprocess.run(
                    ["sudo", "tee", "/etc/resolv.conf"],
                    input=encoded_content,
                    capture_output=True,
                    timeout=10
                )
                if process.returncode == 0:
                    dtslogger.info("Configured host DNS for MagicDNS.")
                    dtslogger.info(
                        "You can now use short hostnames "
                        "(e.g., 'ping <hostname>') to reach devices on the "
                        "Tailscale network."
                    )
                    return True
                else:
                    decoded_stderr = (
                        process.stderr.decode() if process.stderr else ""
                    )
                    dtslogger.debug(
                        f"Failed to write /etc/resolv.conf: {decoded_stderr}"
                    )
                    return False
            except TimeoutExpired:
                dtslogger.debug("Timeout waiting for sudo password")
                return False
            except FileNotFoundError:
                dtslogger.debug("sudo command not found")
                return False
            except Exception as error:
                dtslogger.debug(f"Could not configure host DNS: {error}")
                return False
        except Exception as error:
            dtslogger.debug(f"Could not configure MagicDNS: {error}")
            return False

    @staticmethod
    def _get_tailscale_status_data(
        container: Container
    ) -> tuple[dict, str, str]:
        """Get Tailscale status data.
        
        Args:
            container: The Tailscale container
            
        Returns:
            Tuple of (status_data dict, current_hostname str, tailnet str)
        """
        status_check = container.exec_run(
            "tailscale status --json",
            detach=False
        )
        if status_check.exit_code != 0 or not status_check.output:
            return {}, "", ""
        decoded_output = status_check.output.decode()
        status_data = json.loads(decoded_output)
        self_data = status_data.get("Self", {})
        current_hostname = self_data.get("HostName", "")
        magic_dns_suffix = status_data.get("MagicDNSSuffix", "")
        tailnet = magic_dns_suffix.replace(".ts.net", "")
        return status_data, current_hostname, tailnet

    @staticmethod
    def _extract_duplicates(
        status_data: dict,
        base_hostname: str
    ) -> list[dict]:
        """Extract duplicate devices from status data.
        
        Args:
            status_data: Tailscale status data dictionary
            base_hostname: Base hostname to match against
            
        Returns:
            List of duplicate device dictionaries
        """
        duplicates = []
        self_data = status_data.get("Self", {})
        current_hostname = self_data.get("HostName", "")
        peers = status_data.get("Peer", {})
        # Check self
        if current_hostname.startswith(base_hostname):
            duplicates.append({
                "hostname": current_hostname,
                "ip": self_data.get("TailscaleIPs", [""])[0],
                "online": self_data.get("Online", False),
                "is_self": True,
                "id": self_data.get("ID", ""),
                "node_id": self_data.get("ID", "")
            })
        # Check peers
        escaped_base = re.escape(base_hostname)
        for peer_data in peers.values():
            peer_hostname = peer_data.get("HostName", "")
            if peer_hostname.startswith(base_hostname):
                # Match exact base or base-N pattern
                if (
                    peer_hostname == base_hostname
                    or re.match(rf"^{escaped_base}-\d+$", peer_hostname)
                ):
                    tailscale_ips = peer_data.get("TailscaleIPs", [])
                    duplicates.append({
                        "hostname": peer_hostname,
                        "ip": tailscale_ips[0],
                        "online": peer_data.get("Online", False),
                        "is_self": False,
                        "id": peer_data.get("ID", ""),
                        "node_id": peer_data.get("ID", "")
                    })
        return duplicates

    @staticmethod
    def _check_for_duplicate_hostnames(
        container: Container,
        desired_hostname: str | None
    ) -> tuple[list[dict], str]:
        """Check for duplicate hostnames in the Tailscale network.
        
        Args:
            container: The Tailscale container
            desired_hostname: Hostname to check for duplicates
            
        Returns:
            Tuple of (duplicates list, tailnet name)
        """
        try:
            status_data, current_hostname, tailnet = (
                DTCommand._get_tailscale_status_data(container)
            )
            if not status_data:
                return [], ""
            # Determine the base hostname to check for
            check_hostname = (
                desired_hostname if desired_hostname else current_hostname
            )
            if not check_hostname:
                return [], tailnet
            # Remove any existing numeric suffix to get the base name
            base_hostname = re.sub(r"-\d+$", "", check_hostname)
            duplicates = DTCommand._extract_duplicates(
                status_data,
                base_hostname
            )
            return duplicates, tailnet
        except Exception as error:
            dtslogger.debug(f"Could not check for duplicates: {error}")
            return [], ""

    @staticmethod
    def _delete_duplicate_devices(duplicates: list[dict]) -> int:
        """Delete duplicate devices.
        
        Args:
            duplicates: List of duplicate device dictionaries
            
        Returns:
            Number of successfully deleted devices
        """
        api_key = get_tailscale_api_key()
        if not api_key:
            dtslogger.warning("No Tailscale API key found.")
            log_api_key_info("connect")
            return 0
        # Don't delete the current device
        devices_to_delete = [
            duplicate for duplicate in duplicates if not duplicate["is_self"]
        ]
        if not devices_to_delete:
            return 0
        deleted_count = 0
        for device in devices_to_delete:
            dtslogger.info(
                f"Deleting device \"{device['hostname']}\" ({device['ip']})..."
            )
            if delete_tailscale_device(device["node_id"], api_key):
                deleted_count += 1
                dtslogger.info(f"Deleted {device['hostname']}")
            else:
                dtslogger.warning(f"Failed to delete {device['hostname']}")
        return deleted_count

    @staticmethod
    def _warn_about_duplicates(
        duplicates: list[dict],
        desired_hostname: str,
        tailnet: str
    ) -> bool:
        """Warn user about duplicate hostnames and offer to delete them.
        
        Args:
            duplicates: List of duplicate device dictionaries
            desired_hostname: Desired hostname for the device
            tailnet: Tailscale network name
            
        Returns:
            True if user wants to continue, False otherwise
        """
        if not duplicates:
            return True
        number_of_duplicates = len(duplicates)
        dtslogger.warning(
            f"Found {number_of_duplicates} existing device(s) with a similar "
            "hostname:"
        )
        for duplicate in duplicates:
            status = "online" if duplicate["online"] else "offline"
            self_marker = " (this device)" if duplicate["is_self"] else ""
            print(
                f"  - {duplicate['hostname']} ({duplicate['ip']}) - "
                f"{status}{self_marker}"
            )
        dtslogger.warning(
            "When you reconnect without cleaning up old entries, Tailscale "
            "will create a new device with a numbered suffix "
            f"(e.g., \"{desired_hostname}-1\")."
        )
        # Count devices that can be deleted (not self)
        deletable = [
            duplicate for duplicate in duplicates if not duplicate["is_self"]
        ]
        if deletable and tailnet:
            number_of_deletables = len(deletable)
            dtslogger.info(
                f"Found {number_of_deletables} old device(s) that can be "
                "deleted automatically."
            )
            choice = input("Delete old devices automatically? [y/N]: ")
            if choice.lower() == "y":
                deleted = DTCommand._delete_duplicate_devices(deletable)
                if deleted > 0:
                    dtslogger.info(
                        f"Successfully deleted {deleted} device(s)."
                    )
                    choice_2 = input("Continue with connection? [Y/n]: ")
                    return choice_2.lower() != "n"
                else:
                    dtslogger.warning(
                        "Could not delete devices automatically."
                    )        
            log_old_devices_info()
        choice = input("Continue anyway? [y/N]: ")
        return choice.lower() == "y"

    @staticmethod
    def _clear_tailscale_state(client: DockerClient, machine: str) -> bool:
        """Clear Tailscale authentication state.
        
        Args:
            client: Docker client instance
            machine: Machine identifier
            
        Returns:
            True if state was cleared successfully, False otherwise
        """
        dtslogger.info("Clearing Tailscale state...")
        try:
            result = client.containers.run(
                "alpine:latest",
                [
                    "sh",
                    "-c",
                    "rm -rf /var/lib/tailscale/* && echo Done"
                ],
                volumes={
                    "/var/lib": {
                        "bind": "/var/lib",
                        "mode": "rw"
                    }
                },
                remove=True,
                detach=False,
            )
            if result and b"Done" in result:
                dtslogger.info("State cleared successfully.")
            else:
                dtslogger.info("State clearing completed.")
            return True
        except Exception as error:
            dtslogger.warning(f"Could not clear state automatically: {error}")
            # Clean up any leftover containers
            try:
                for container in client.containers.list(
                    all=True,
                    filters={
                        "ancestor": "alpine:latest",
                        "status": "created"
                    }
                ):
                    container.remove(force=True)
            except Exception:
                pass
            if machine == DEFAULT_MACHINE:
                dtslogger.info(
                    "You may need to manually run: sudo rm -rf "
                    "/var/lib/tailscale"
                )
            else:
                dtslogger.info(
                    "You may need to manually clear /var/lib/tailscale"
                    " on the target host"
                )
            return False

    @staticmethod
    def _try_delete_current_device(
        container: Container,
        api_key: str
    ) -> bool:
        """Try to delete the current device via API.
        
        Args:
            container: The Tailscale container
            api_key: Tailscale API key
            
        Returns:
            True if deletion succeeded, False otherwise
        """
        try:
            status_check = container.exec_run(
                "tailscale status --json",
                detach=False
            )
            if status_check.exit_code != 0 or not status_check.output:
                return False
            decoded_output = status_check.output.decode()
            status_data = json.loads(decoded_output)
            self_data = status_data.get("Self", {})
            current_node_id = self_data.get("ID", "")
            current_hostname = self_data.get("HostName", "")
            if not current_node_id:
                return False
            dtslogger.info(
                f"Deleting current device \"{current_hostname}\" to free up "
                f"hostname..."
            )
            if delete_tailscale_device(current_node_id, api_key):
                dtslogger.info(
                    "Successfully deleted device from the Tailscale network."
                )
                # Give Tailscale API a moment to sync
                time.sleep(2)
                return True
            dtslogger.warning(
                "Could not delete device via API. The hostname may not be "
                "freed."
            )
            return False
        except Exception as error:
            dtslogger.debug(f"Could not delete via API: {error}")
            return False

    @staticmethod
    def _try_logout_container(container: Container) -> bool:
        """Try to logout from Tailscale in the container.
        
        Args:
            container: The Tailscale container
            
        Returns:
            True if logout succeeded, False otherwise
        """
        dtslogger.info("Logging out from Tailscale...")
        try:
            # Start it if stopped
            if container.status != "running":
                container.start()
                time.sleep(2)
                container.reload()
            # Run logout
            logout_result = container.exec_run(
                "tailscale logout",
                detach=False
            )
            if logout_result.exit_code == 0:
                dtslogger.info("Logged out successfully.")
                time.sleep(2)
                return True
            dtslogger.debug("Logout command returned non-zero.")
            return False
        except Exception as error:
            dtslogger.debug(f"Could not logout: {error}")
            return False

    @staticmethod
    def _prompt_user_for_container_removal() -> bool:
        """Ask user if they want to remove existing container.
        
        Returns:
            True if user wants to remove container, False otherwise
        """
        dtslogger.warning("Tailscale container is already running.")
        choice = input(
            "Remove the existing container and create a new one? [y/N]: "
        )
        return choice.lower() == "y"

    @staticmethod
    def _handle_existing_container(
        client: DockerClient,
        authkey: str | None,
        machine: str
    ) -> bool:
        """Handle existing Tailscale container.
        
        Args:
            client: Docker client instance
            authkey: Optional Tailscale authkey
            machine: Machine identifier
            
        Returns:
            True if should continue with setup, False otherwise
        """
        try:
            existing_container = client.containers.get("tailscaled")
            existing_container.reload()
            if existing_container.status == "running":
                # Prompt user for removal first
                if not DTCommand._prompt_user_for_container_removal():
                    dtslogger.info("Aborted.")
                    return False
                # Try to delete current device via API, fallback to logout
                api_key = get_tailscale_api_key()
                if api_key:
                    DTCommand._try_delete_current_device(
                        existing_container,
                        api_key
                    )
                else:
                    DTCommand._try_logout_container(existing_container)
            else:
                dtslogger.info("Removing stopped Tailscale container...")
            existing_container.remove(force=True)
            if not authkey:
                DTCommand._clear_tailscale_state(client, machine)
            return True
        except NotFound:
            if not authkey:
                DTCommand._clear_tailscale_state(client, machine)
            return True

    @staticmethod
    def _check_tun_conflicts(client: DockerClient) -> bool:
        """Check for conflicts with /dev/net/tun.
        
        Args:
            client: Docker client instance
            
        Returns:
            True if safe to proceed, False if user wants to abort
        """
        try:
            # Check if /dev/net/tun exists and is accessible
            result = client.containers.run(
                "alpine:latest",
                [
                    "sh",
                    "-c",
                    "test -c /dev/net/tun && echo OK || echo FAIL"
                ],
                volumes={
                    "/dev/net/tun": {
                        "bind": "/dev/net/tun",
                        "mode": "rw"
                    }
                },
                privileged=True,
                remove=True,
                detach=False,
            )
            if result and b"OK" in result:
                dtslogger.debug("/dev/net/tun is accessible")
            return True
        except Exception as error:
            dtslogger.debug(f"Could not check for TUN conflicts: {error}")
            # Clean up any leftover containers
            try:
                for container in client.containers.list(
                    all=True,
                    filters={
                        "ancestor": "alpine:latest",
                        "status": "created"
                    }
                ):
                    container.remove(force=True)
            except Exception:
                pass
            return True

    @staticmethod
    def _cleanup_orphaned_containers(client: DockerClient) -> None:
        """Clean up orphaned alpine containers from previous runs.
        
        Args:
            client: Docker client instance
        """
        try:
            orphaned = client.containers.list(
                all=True,
                filters={
                    "ancestor": "alpine:latest",
                    "status": "created"
                }
            )
            if orphaned:
                number_of_orphaned = len(orphaned)
                dtslogger.debug(
                    f"Cleaning up {number_of_orphaned} orphaned alpine "
                    "containers..."
                )
                for container in orphaned:
                    try:
                        container.remove(force=True)
                    except Exception:
                        pass
        except Exception as error:
            dtslogger.debug(f"Could not clean up orphaned containers: {error}")

    @staticmethod
    def _create_container(client: DockerClient) -> Container | None:
        """Create and start the Tailscale container.
        
        Args:
            client: Docker client instance
            
        Returns:
            Container instance if successful, None otherwise
        """
        environment = {
            "TS_STATE_DIR": "/var/lib/tailscale"
        }
        try:
            container = client.containers.run(
                "tailscale/tailscale",
                command=[
                    "sh",
                    "-c",
                    (
                        "ip link delete tailscale0 2>/dev/null || true && "
                        "mkdir -p /var/run/tailscale && "
                        "rm -f /var/run/tailscale/tailscaled.sock && "
                        "tailscaled "
                        "--socket=/var/run/tailscale/tailscaled.sock "
                        "--statedir=/var/lib/tailscale --tun=tailscale0"
                    )
                ],
                name="tailscaled",
                detach=True,
                network_mode="host",
                volumes={
                    "/var/lib/tailscale": {
                        "bind": "/var/lib/tailscale",
                        "mode": "rw"
                    },
                    "/dev/net/tun": {
                        "bind": "/dev/net/tun",
                        "mode": "rw"
                    },
                },
                cap_add=["NET_ADMIN", "NET_RAW"],
                environment=environment,
                restart_policy={
                    "Name": "unless-stopped"
                },
            )
            dtslogger.info(
                "Tailscale container started successfully: "
                f"{container.id[:12]}"
            )
            return container
        except Exception as error:
            dtslogger.error(f"Failed to start Tailscale container: {error}")
            return None

    @staticmethod
    def _start_container(client: DockerClient) -> Container | None:
        """Start Tailscale container with kernel TUN for seamless connectivity.
        
        Args:
            client: Docker client instance
            
        Returns:
            Container instance if successful, None otherwise
        """
        dtslogger.info("Starting Tailscale container with kernel TUN mode...")
        # Check for conflicts with /dev/net/tun
        if not DTCommand._check_tun_conflicts(client):
            dtslogger.info("Aborted.")
            return None
        # Create and start the container
        return DTCommand._create_container(client)

    @staticmethod
    def _verify_container_running(container: Container) -> bool:
        """Verify container is running.
        
        Args:
            container: The Tailscale container
            
        Returns:
            True if container is running, False otherwise
        """
        # Wait and check multiple times to detect crash loops
        max_checks = 5
        for check in range(max_checks):
            time.sleep(2 if check == 0 else 1)
            container.reload()
            status = container.status
            if status == "running":
                # Container is running, good
                if check > 0:
                    dtslogger.debug(
                        f"Container stabilized after {check + 1} checks"
                    )
                return True
            elif status in ("restarting", "created"):
                # Container is still starting up, wait a bit more
                if check < max_checks - 1:
                    dtslogger.debug(
                        f"Container status: {status}, waiting... "
                        f"({check + 1}/{max_checks})"
                    )
                    continue
            # Container is in a bad state (exited, dead, etc.) or still 
            # restarting after max checks
            dtslogger.error(
                f"Container failed to start properly. Status: {status}"
            )
            try:
                logs = container.logs(tail=50)
                decoded_logs = logs.decode()
                if decoded_logs:
                    dtslogger.error(f"Container logs:\n{decoded_logs}")
            except Exception:
                pass
            break
        return False

    @staticmethod
    def _check_api_for_duplicates_before_auth(
        hostname: str | None
    ) -> bool:
        """Check for duplicate devices via API before authentication.
        
        Args:
            hostname: Hostname to check for duplicates
            
        Returns:
            True if should continue, False if user wants to abort
        """
        if not hostname:
            # No hostname specified, nothing to check
            return True
        api_key = get_tailscale_api_key()
        if not api_key:
            log_api_key_info("connect")
            dtslogger.warning(
                f"Without duplicate cleanup, Tailscale may create a numbered "
                f"device (e.g., '{hostname}-1')."
            )
            choice = input(
                "Continue without duplicate check? [y/N]: "
            )
            return choice.lower() == "y"
        dtslogger.info(
            f"Checking for existing devices with hostname '{hostname}'..."
        )
        duplicates = find_devices_by_hostname(hostname, api_key)
        if not duplicates:
            dtslogger.debug("No duplicate devices found.")
            return True
        # Found duplicates - warn and offer to delete
        number_of_duplicates = len(duplicates)
        dtslogger.warning(
            f"Found {number_of_duplicates} existing device(s) with hostname "
            f"'{hostname}':"
        )
        for duplicate in duplicates:
            status = "online" if duplicate["online"] else "offline"
            print(
                f"  - {duplicate['hostname']} ({duplicate['ip']}) - {status}"
            )
        dtslogger.warning(
            "If not deleted, Tailscale will create a new device with a "
            f"numbered suffix (e.g., '{hostname}-1')."
        )
        choice = input(
            f"Delete {number_of_duplicates} existing device(s) before "
            "connecting? [Y/n]: "
        )
        if choice.lower() == "n":
            dtslogger.info("Skipping deletion.")
            choice_2 = input("Continue with connection anyway? [y/N]: ")
            return choice_2.lower() == "y"
        # Delete devices
        deleted_count = 0
        for device in duplicates:
            dtslogger.info(
                f"Deleting device '{device['hostname']}' ({device['ip']})..."
            )
            if delete_tailscale_device(device["node_id"], api_key):
                deleted_count += 1
                dtslogger.info(f"Deleted {device['hostname']}")
            else:
                dtslogger.warning(f"Failed to delete {device['hostname']}")
        if deleted_count > 0:
            dtslogger.info(
                f"Successfully deleted {deleted_count} device(s). "
                "Proceeding with connection..."
            )
            return True
        dtslogger.warning("Could not delete any devices.")
        choice = input("Continue anyway? [y/N]: ")
        return choice.lower() == "y"

    @staticmethod
    def _check_already_authenticated(
        container: Container,
        authkey: str | None,
        machine: str
    ) -> bool:
        """Check if already authenticated.
        
        Args:
            container: The Tailscale container
            authkey: Optional Tailscale authkey
            machine: Machine identifier
            
        Returns:
            True if already authenticated, False otherwise
        """
        dtslogger.info("Checking current authentication status...")
        # Wait a bit and retry multiple times
        # Tailscale can take time to initialize
        max_attempts = 15  # 30 seconds total
        for attempt in range(max_attempts):
            if attempt > 0:
                time.sleep(2)
            # Try to check status, but handle container restart conflicts
            try:
                status_check = container.exec_run(
                    "tailscale status",
                    detach=False
                )
            except APIError as error:
                # Container might be restarting
                error_message = str(error)
                if "restarting" in error_message.lower():
                    if attempt < max_attempts - 1:
                        dtslogger.debug(
                            "Container is restarting, waiting... "
                            f"({attempt + 1}/{max_attempts})"
                        )
                    continue
                # Other API errors should be raised
                raise
            if status_check.exit_code != 0 or not status_check.output:
                if attempt < max_attempts - 1:
                    dtslogger.debug(
                        "Waiting for Tailscale to initialize... "
                        f"({attempt + 1}/{max_attempts})"
                    )
                continue
            decoded_output = status_check.output.decode()
            if "100." not in decoded_output:
                if attempt < max_attempts - 1:
                    dtslogger.debug(
                        "Waiting for Tailscale IP... "
                        f"({attempt + 1}/{max_attempts})"
                    )
                continue
            # Successfully authenticated
            if authkey:
                dtslogger.info(
                    "Successfully connected to the Tailscale network using "
                    "authkey."
                )
            else:
                dtslogger.info("Already connected to the Tailscale network.")
            print(
                "\nCurrent status:\n"
                f"{decoded_output}"
            )
            # Get and display Tailscale IP
            DTCommand._get_and_log_tailscale_ip(container, decoded_output)
            # Configure host DNS for MagicDNS
            DTCommand._configure_host_magicdns(container, machine)
            return True
        return False

    @staticmethod
    def _get_and_log_tailscale_ip(
        container: Container,
        status_output: str
    ) -> str | None:
        """Get and log Tailscale IP address.
        
        Args:
            container: The Tailscale container
            status_output: Output from 'tailscale status' command
            
        Returns:
            The Tailscale IP address or None if not found
        """
        # Try to get IP using tailscale ip command
        ip_result = container.exec_run("tailscale ip -4", detach=False)
        tailscale_ip = None
        if ip_result.exit_code == 0 and ip_result.output:
            decoded_output = ip_result.output.decode()
            tailscale_ip = decoded_output.strip()
        # Fallback: extract IP from status output
        if not tailscale_ip:
            ip_match = re.search(r'100\.\d+\.\d+\.\d+', status_output)
            if ip_match:
                tailscale_ip = ip_match.group(0)
        if tailscale_ip:
            dtslogger.info(f"Tailscale IP: {tailscale_ip}")
        else:
            dtslogger.warning("Could not retrieve Tailscale IP address")
        return tailscale_ip

    @staticmethod
    def _stream_auth_output(
        container: Container,
        exec_id: dict
    ) -> str | None:
        """Stream exec output and look for auth URL.
        
        Args:
            container: The Tailscale container
            exec_id: Execution ID dictionary
            
        Returns:
            Authentication URL if found, None otherwise
        """
        exec_stream = container.client.api.exec_start(
            exec_id["Id"],
            stream=True,
            demux=False
        )
        dtslogger.info("Starting authentication process...")
        dtslogger.info("Waiting for authentication URL...")
        auth_url = None
        url_opened = False
        start_time = time.time()
        try:
            for chunk in exec_stream:
                if not chunk:
                    continue
                line = chunk.decode("utf-8", errors="ignore")
                urls_in_line = re.findall(r"https?://[^\s\"'<>]+", line)
                for candidate_url in urls_in_line:
                    parsed = urlparse(candidate_url)
                    if (
                        parsed.scheme == "https"
                        and parsed.hostname == "login.tailscale.com"
                    ):
                        if not auth_url:
                            auth_url = candidate_url.strip()
                            if not url_opened:
                                DTCommand._open_auth_url(auth_url)
                                url_opened = True
                        break
                current_time = time.time()
                if (
                    (current_time - start_time > 15)
                    or (auth_url and current_time - start_time > 2)
                ):
                    break
        except Exception as error:
            dtslogger.debug(f"Stream reading ended: {error}")
        return auth_url

    @staticmethod
    def _check_logs_for_auth_url(container: Container) -> str | None:
        """Check container logs for authentication URL.
        
        Args:
            container: The Tailscale container
            
        Returns:
            Authentication URL if found, None otherwise
        """
        dtslogger.debug("Checking container logs for auth URL...")
        for attempt in range(3):
            time.sleep(2)
            container.reload()
            logs = container.logs(tail=100)
            decoded_logs = logs.decode("utf-8", errors="ignore")
            dtslogger.debug(
                f"Container logs (attempt {attempt + 1}):\n{decoded_logs}"
            )
            for line in decoded_logs.split("\n"):
                for candidate in re.findall(r"https://[^\s]+", line):
                    parsed_url = urlparse(candidate)
                    if (
                        parsed_url.scheme == "https"
                        and parsed_url.hostname == "login.tailscale.com"
                    ):
                        print(candidate)
                        return candidate.strip()
        return None

    @staticmethod
    def _get_auth_url(
        container: Container,
        hostname: str | None
    ) -> str | None:
        """Get authentication URL from Tailscale.
        
        Args:
            container: The Tailscale container
            hostname: Optional hostname for the device
            
        Returns:
            Authentication URL if found, None otherwise
        """
        command = "tailscale up"
        if hostname:
            command += f" --hostname={hostname}"
        command += " 2>&1"
        exec_id = container.client.api.exec_create(
            container.id,
            ("sh", "-c", command),
            stdout=True,
            stderr=True,
            stdin=False,
            tty=False
        )
        # Try to get URL from stream
        auth_url = DTCommand._stream_auth_output(container, exec_id)
        # Fallback: check container logs
        if not auth_url:
            auth_url = DTCommand._check_logs_for_auth_url(container)
            if auth_url:
                DTCommand._open_auth_url(auth_url)
        return auth_url

    @staticmethod
    def _open_auth_url(auth_url: str) -> None:
        """Extract and open authentication URL in browser.
        
        Args:
            auth_url: The authentication URL string
        """
        url_match = re.search(
            r"https://login\.tailscale\.com/[^\s]+",
            auth_url
        )
        if url_match:
            url = url_match.group(0)
            dtslogger.info(f"Navigate to {url}.")
            try:
                webbrowser.open(url)
            except Exception as error:
                dtslogger.warning(
                    f"Could not open browser automatically: {error}"
                )
            return
        dtslogger.info(
            "Please navigate to the URL above to complete authentication."
        )

    @staticmethod
    def _wait_for_connection(
        container: Container,
        hostname: str | None,
        machine: str
    ) -> bool:
        """Wait for Tailscale connection to be established.
        
        Args:
            container: The Tailscale container
            hostname: Optional hostname for the device
            machine: Machine identifier
            
        Returns:
            True if connection established, False on timeout
        """
        dtslogger.info("Waiting for authentication to complete...")
        max_wait = 120  # 2 minutes total
        waited = 0
        check_interval = 3  # Check every 3 seconds
        while waited < max_wait:
            time.sleep(check_interval)
            waited += check_interval
            try:
                status_result = container.exec_run(
                    "tailscale status",
                    detach=False
                )
            except Exception as error:
                dtslogger.debug(f"Status check failed: {error}")
                if waited % 15 == 0:
                    dtslogger.info(
                        "Still waiting for authentication... "
                        f"({waited}s/{max_wait}s)"
                    )
                continue
            if status_result.exit_code != 0:
                dtslogger.debug(
                    f"Status command exit code: {status_result.exit_code}"
                )
                if waited % 15 == 0:
                    dtslogger.info(
                        "Still waiting for authentication... "
                        f"({waited}s/{max_wait}s)"
                    )
                continue
            if not status_result.output:
                dtslogger.debug("Status command returned no output")
                if waited % 15 == 0:
                    dtslogger.info(
                        "Still waiting for authentication... "
                        f"({waited}s/{max_wait}s)"
                    )
                continue
            decoded_output = status_result.output.decode()
            dtslogger.debug(
                f"Status check ({waited}s): {decoded_output[:100]}..."
            )
            # Check if we have a valid Tailscale IP assigned
            if "100." in decoded_output:
                dtslogger.info(
                    "Successfully connected to the Tailscale network."
                )
                if hostname:
                    dtslogger.info(f"Hostname: {hostname}")                    
                # Get and display Tailscale IP
                DTCommand._get_and_log_tailscale_ip(container, decoded_output)
                # Configure host DNS for MagicDNS
                DTCommand._configure_host_magicdns(container, machine)
                return True
            # Show progress every 15 seconds
            if waited % 15 == 0:
                dtslogger.info(
                    "Still waiting for authentication... "
                    f"({waited}s/{max_wait}s)"
                )
        dtslogger.error(
            "Timeout waiting for authentication. Please try again."
        )
        return False

    @staticmethod
    def _check_if_already_authorized(
        container: Container,
        machine: str
    ) -> bool:
        """Check if machine is already authorized and wait for connection.
        
        Args:
            container: The Tailscale container
            machine: Machine identifier
            
        Returns:
            True if authorized and connected, False otherwise
        """
        dtslogger.debug(
            "No auth URL found. Checking if already authorized..."
        )
        time.sleep(3)
        logs = container.logs(tail=50)
        decoded_logs = logs.decode("utf-8", errors="ignore")
        if "machineAuthorized=true" not in decoded_logs:
            return False
        dtslogger.info(
            "Machine is already authorized! Waiting for connection..."
        )
        # Wait for connection to establish
        max_attempts = 40  # 40 attempts × 3 seconds = 2 minutes
        for attempt in range(max_attempts):
            time.sleep(3)
            status_check = container.exec_run(
                "tailscale status",
                detach=False
            )
            if status_check.exit_code != 0 or not status_check.output:
                if (attempt + 1) % 5 == 0:  # Log every 15 seconds
                    dtslogger.info(
                        "Still waiting... "
                        f"({(attempt + 1) * 3}s/{max_attempts * 3}s)"
                    )
                continue
            decoded_output = status_check.output.decode()
            if "100." in decoded_output:
                dtslogger.info(
                    "Successfully connected to the Tailscale network."
                )
                print(
                    "\nCurrent status:\n"
                    f"{decoded_output}"
                )
                # Get and display Tailscale IP
                DTCommand._get_and_log_tailscale_ip(container, decoded_output)
                # Configure host DNS for MagicDNS
                DTCommand._configure_host_magicdns(container, machine)
                return True
        dtslogger.error("Timeout waiting for connection.")
        return False

    @staticmethod
    def _authenticate_interactive(
        container: Container,
        hostname: str | None,
        machine: str
    ) -> bool:
        """Authenticate using interactive browser login.
        
        Args:
            container: The Tailscale container
            hostname: Optional hostname for the device
            machine: Machine identifier
            
        Returns:
            True if authentication succeeded, False otherwise
        """
        dtslogger.info(
            "Authenticating with Tailscale using interactive browser login..."
        )
        try:
            auth_url = DTCommand._get_auth_url(
                container,
                hostname
            )
            if auth_url:
                # URL already opened in _get_auth_url, just wait for connection
                return DTCommand._wait_for_connection(
                    container,
                    hostname,
                    machine
                )
            # No auth URL found - check if already authorized
            if DTCommand._check_if_already_authorized(container, machine):
                return True
            dtslogger.error("Could not find authentication URL in output.")
            dtslogger.info(
                "Please check if Tailscale is already authenticated or check "
                "container logs."
            )
        except Exception as error:
            dtslogger.error(f"Failed to authenticate with Tailscale: {error}")
        return False

    @staticmethod
    def _authenticate_with_authkey(
        container: Container,
        authkey: str,
        hostname: str | None,
        machine: str
    ) -> bool:
        """Authenticate using authkey.
        
        State is cleared before container start, so this will use the authkey
        to connect. We don't use --reset to allow WantRunning=true to be saved
        for auto-reconnect after reboot.
        
        Args:
            container: The Tailscale container
            authkey: Tailscale authentication key
            hostname: Optional hostname for the device
            machine: Machine identifier
            
        Returns:
            True if authentication succeeded, False otherwise
        """
        dtslogger.info("Authenticating with Tailscale using authkey...")
        try:
            command = f"tailscale up --authkey={authkey}"
            if hostname:
                command += f" --hostname={hostname}"
            exec_result = container.exec_run(command, detach=False)
            if exec_result.exit_code == 0:
                dtslogger.info(
                    "Successfully connected to the Tailscale network."
                )
                if hostname:
                    dtslogger.info(f"Hostname: {hostname}")
                # Configure host DNS for MagicDNS
                DTCommand._configure_host_magicdns(container, machine)
                return True
            decoded_output = exec_result.output.decode()
            dtslogger.error(f"Failed to authenticate: {decoded_output}")
        except Exception as error:
            dtslogger.error(f"Failed to authenticate with Tailscale: {error}")
        return False

    @staticmethod
    def command(_: DTShell, args: list[str]) -> None:
        """Main command entry point.
        
        Args:
            _: DTShell instance (unused)
            args: Command line arguments
        """
        prog = "dts tailscale connect"
        parser = ArgumentParser(prog=prog)
        parser.add_argument(
            "-H",
            "--machine",
            default=DEFAULT_MACHINE,
            help="Docker socket or hostname where to run Tailscale",
        )
        parser.add_argument(
            "--authkey",
            type=str,
            default=None,
            help=(
                "Tailscale authentication key "
                "(if not provided, will use interactive browser login)"
            ),
        )
        parser.add_argument(
            "--hostname",
            type=str,
            default=None,
            help="Hostname to use on the Tailscale network",
        )
        parsed = parser.parse_args(args)
        machine = parsed.machine
        authkey = parsed.authkey
        hostname = parsed.hostname
        # Connect to Docker
        client = resolve_and_connect_docker(machine)
        if not client:
            return
        # If no hostname provided, detect it from Docker host
        # This is what Tailscale will auto-detect during authentication
        if not hostname and not authkey:
            try:
                result = client.containers.run(
                    "alpine:latest",
                    "hostname",
                    network_mode="host",
                    remove=True,
                    detach=False,
                )
                if result:
                    decoded_result = result.decode()
                    hostname = decoded_result.strip()
                    dtslogger.debug(
                        f"Detected Docker host hostname: {hostname}"
                    )
            except Exception as error:
                dtslogger.debug(
                    f"Could not detect Docker host hostname: {error}"
                )
        # Clean up orphaned containers from previous runs
        DTCommand._cleanup_orphaned_containers(client)
        # Handle existing container
        should_continue = DTCommand._handle_existing_container(
            client,
            authkey,
            machine
        )
        if not should_continue:
            return
        # Check for duplicate devices via API before creating container
        # Always check even if we deleted current device, to catch other old 
        # ones
        if not authkey:
            if not DTCommand._check_api_for_duplicates_before_auth(hostname):
                dtslogger.info("Aborted.")
                return
        # Start container
        container = DTCommand._start_container(client)
        if not container:
            return
        # Verify it's running
        if not DTCommand._verify_container_running(container):
            return
        # Check if already authenticated
        if DTCommand._check_already_authenticated(container, authkey, machine):
            return
        # Authenticate based on whether authkey is provided
        if authkey:
            DTCommand._authenticate_with_authkey(
                container,
                authkey,
                hostname,
                machine
            )
        else:
            DTCommand._authenticate_interactive(
                container,
                hostname,
                machine
            )
