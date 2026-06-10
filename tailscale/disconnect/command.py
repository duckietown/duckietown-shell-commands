import json
import subprocess
from argparse import ArgumentParser
from subprocess import TimeoutExpired

from docker import DockerClient
from docker.errors import NotFound
from docker.models.containers import Container
from dt_shell import DTCommandAbs, DTShell, dtslogger

from utils.docker_utils import DEFAULT_MACHINE
from utils.tailscale_utils import (
    delete_tailscale_device,
    get_tailscale_api_key,
    log_api_key_info,
    log_old_devices_info,
    resolve_and_connect_docker,
)


class DTCommand(DTCommandAbs):
    help = "Disconnects from a Tailscale network"

    @staticmethod
    def _restore_original_dns(machine: str) -> bool:
        """Restore original DNS configuration by removing Tailscale DNS.
        
        Args:
            machine: Machine identifier
            
        Returns:
            True if restoration was successful or skipped, False on error
        """
        if machine != DEFAULT_MACHINE:
            dtslogger.debug(
                "Skipping host DNS restoration for remote machine."
            )
            return True
        try:
            # Read current resolv.conf
            with open("/etc/resolv.conf", "r") as file:
                current_content = file.read()
        except Exception as error:
            dtslogger.debug(f"Could not read /etc/resolv.conf: {error}")
            return True  # Not a critical error
        # Check if Tailscale DNS is configured
        if "100.100.100.100" not in current_content:
            dtslogger.debug(
                "Tailscale DNS not found in /etc/resolv.conf, "
                "skipping restoration."
            )
            return True
        # Ask user if they want to restore DNS
        dtslogger.info(
            "Tailscale DNS configuration detected in /etc/resolv.conf."
        )
        choice = input(
            "Restore original DNS configuration (remove Tailscale DNS)? "
            "[Y/n]: "
        )
        if choice.lower() == "n":
            dtslogger.info("Skipped DNS restoration.")
            return True
        # Extract fallback nameserver (not 100.100.100.100)
        fallback_nameserver = None
        for line in current_content.split("\n"):
            if (
                line.startswith("nameserver")
                and "100.100.100.100" not in line
            ):
                split_line = line.split()
                fallback_nameserver = (
                    split_line[1] if len(split_line) > 1 else None
                )
                break
        if not fallback_nameserver:
            fallback_nameserver = "8.8.8.8"  # Fallback to Google DNS
        # Create new resolv.conf without Tailscale DNS
        new_content = f"nameserver {fallback_nameserver}\n"
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
                dtslogger.info("Restored original DNS configuration.")
                return True
            else:
                decoded_stderr = process.stderr.decode() if process.stderr else ""
                dtslogger.warning(
                    f"Failed to restore DNS configuration: {decoded_stderr}"
                )
                return False
        except TimeoutExpired:
            dtslogger.warning("Timeout waiting for sudo password")
            return False
        except FileNotFoundError:
            dtslogger.debug("sudo command not found")
            return False
        except Exception as error:
            dtslogger.warning(f"Could not restore DNS: {error}")
            return False

    @staticmethod
    def _get_container(client: DockerClient) -> Container | None:
        """Get the Tailscale container if it exists.
        
        Args:
            client: Docker client instance
            
        Returns:
            Container instance if found, None otherwise
        """
        try:
            return client.containers.get("tailscaled")
        except NotFound:
            dtslogger.error("No Tailscale container found.")
            return None

    @staticmethod
    def _ensure_container_running(container: Container) -> bool:
        """Ensure container is running, start if needed.
        
        Args:
            container: The Tailscale container
            
        Returns:
            True if container was stopped and we started it, False otherwise
        """
        container.reload()
        if container.status == "running":
            return False
        dtslogger.info(
            f"Container is not running (status: {container.status}), "
            "starting it temporarily..."
        )
        try:
            container.start()
            container.reload()
            return True
        except Exception as error:
            dtslogger.warning(
                f"Failed to start container: {error}. "
                "Skipping disconnect."
            )
            raise

    @staticmethod
    def _get_device_info(container: Container) -> tuple[str, str]:
        """Get device node_id and hostname from Tailscale status.
        
        Args:
            container: The Tailscale container
            
        Returns:
            Tuple of (node_id, hostname)
        """
        status_check = container.exec_run(
            "tailscale status --json",
            detach=False
        )
        if status_check.exit_code != 0 or not status_check.output:
            return "", ""
        decoded_output = status_check.output.decode()
        status_data = json.loads(decoded_output)
        self_data = status_data.get("Self", {})
        node_id = self_data.get("ID", "")
        hostname = self_data.get("HostName", "")
        return node_id, hostname

    @staticmethod
    def _try_delete_device_via_api(
        container: Container,
        api_key: str
    ) -> bool:
        """Try to delete the current device via Tailscale API.
        
        Args:
            container: The Tailscale container
            api_key: Tailscale API key
            
        Returns:
            True if successfully deleted, False otherwise
        """
        try:
            node_id, hostname = DTCommand._get_device_info(container)
            if not node_id:
                dtslogger.warning("Could not get device info for deletion.")
                return False
            dtslogger.info(
                f"Deleting device '{hostname}' to free hostname..."
            )
            if delete_tailscale_device(node_id, api_key):
                dtslogger.info(
                    "Successfully deleted device from the Tailscale network."
                )
                return True
            dtslogger.warning(
                "Could not delete device via API. The API key may lack "
                "'devices:write' permission."
            )
            log_old_devices_info()
            return False
        except Exception as error:
            dtslogger.debug(f"Could not delete via API: {error}")
            return False

    @staticmethod
    def _logout_from_tailscale(container: Container) -> bool:
        """Logout from the Tailscale network.
        
        Args:
            container: The Tailscale container
            
        Returns:
            True if successfully logged out, False otherwise
        """
        dtslogger.info("Logging out from the Tailscale network...")
        try:
            exec_result = container.exec_run(
                "tailscale logout",
                detach=False
            )
            if exec_result.exit_code == 0:
                dtslogger.info(
                    "Successfully logged out from the Tailscale network."
                )
                return True
            decoded_output = exec_result.output.decode()
            dtslogger.warning(
                f"Logout command returned non-zero: {decoded_output}"
            )
            return False
        except Exception as error:
            dtslogger.warning(f"Failed to run logout command: {error}")
            return False

    @staticmethod
    def _stop_container_if_needed(
        container: Container,
        was_stopped: bool
    ) -> None:
        """Stop container if we started it temporarily.
        
        Args:
            container: The Tailscale container
            was_stopped: Whether container was stopped when we started
        """
        if not was_stopped:
            return
        try:
            container.stop(timeout=5)
        except Exception as error:
            dtslogger.warning(f"Failed to stop container: {error}")

    @staticmethod
    def _disconnect_tailscale(container: Container) -> None:
        """Disconnect from Tailscale network and delete device to free hostname.
        
        Args:
            container: The Tailscale container
        """
        # Ensure container is running
        try:
            was_stopped = DTCommand._ensure_container_running(container)
        except Exception:
            return
        # Try to delete via API first (frees the hostname)
        api_key = get_tailscale_api_key()
        deleted_via_api = False
        if api_key:
            deleted_via_api = DTCommand._try_delete_device_via_api(
                container,
                api_key
            )
        else:
            log_api_key_info("disconnect")
            dtslogger.warning(
                "The device will be logged out but not deleted from the "
                "Tailscale network."
            )
        # Fallback: logout if API deletion failed or no API key
        if not deleted_via_api:
            DTCommand._logout_from_tailscale(container)
        # Stop container if we started it
        DTCommand._stop_container_if_needed(container, was_stopped)

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
    def _remove_container(container: Container) -> None:
        """Remove the Tailscale container.
        
        Args:
            container: The Tailscale container
        """
        dtslogger.info("Removing Tailscale container...")
        try:
            container.remove(force=True)
            dtslogger.info("Tailscale container removed.")
        except Exception as error:
            dtslogger.error(f"Failed to remove container: {error}")

    @staticmethod
    def command(_: DTShell, args: list[str]) -> None:
        """Main command entry point.
        
        Args:
            _: DTShell instance (unused)
            args: Command line arguments
        """
        prog = "dts tailscale disconnect"
        parser = ArgumentParser(prog=prog)
        parser.add_argument(
            "-H",
            "--machine",
            default=DEFAULT_MACHINE,
            help="Docker socket or hostname where Tailscale is running",
        )
        parsed = parser.parse_args(args)
        machine = parsed.machine
        # Connect to Docker
        client = resolve_and_connect_docker(machine)
        if not client:
            return
        # Clean up orphaned containers from previous runs
        DTCommand._cleanup_orphaned_containers(client)
        # Get container
        container = DTCommand._get_container(client)
        if not container:
            return
        # Ask for confirmation
        dtslogger.warning(
            "This will disconnect from Tailscale and remove the container."
        )
        choice = input("Are you sure you want to disconnect? [y/N]: ")
        if choice.lower() != "y":
            dtslogger.info("Aborted.")
            return
        # Disconnect from Tailscale
        DTCommand._disconnect_tailscale(container)
        # Remove container
        DTCommand._remove_container(container)
        # Restore original DNS configuration
        DTCommand._restore_original_dns(machine)
