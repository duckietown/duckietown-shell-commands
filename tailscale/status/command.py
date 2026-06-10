import json
import re
from argparse import ArgumentParser
from json import JSONDecodeError

from docker import DockerClient
from docker.errors import NotFound
from docker.models.containers import Container
from dt_shell import DTCommandAbs, DTShell, dtslogger

from utils.docker_utils import DEFAULT_MACHINE
from utils.tailscale_utils import resolve_and_connect_docker


class DTCommand(DTCommandAbs):
    help = "Shows the Tailscale connection status"

    @staticmethod
    def _get_container(client: DockerClient, machine: str) -> Container | None:
        """Get the Tailscale container if it exists.
        
        Args:
            client: Docker client instance
            machine: Machine identifier
            
        Returns:
            Container instance if found, None otherwise
        """
        try:
            return client.containers.get("tailscaled")
        except NotFound:
            dtslogger.info("Tailscale container not found.")
            machine_arg = (
                f" -H {machine}"
                if machine != DEFAULT_MACHINE
                else ""
            )
            dtslogger.info(
                f"Run 'dts tailscale connect{machine_arg}' to set it up."
            )
            return None

    @staticmethod
    def _check_container_running(container: Container) -> bool:
        """Check if container is running.
        
        Args:
            container: The Tailscale container
            
        Returns:
            True if container is running, False otherwise
        """
        container.reload()
        dtslogger.info(f"Container status: {container.status}")
        if container.status != "running":
            dtslogger.warning("Tailscale container is not running.")
            return False
        return True

    @staticmethod
    def _check_device_authorization(container: Container) -> bool:
        """Check if device needs authorization.
        
        Args:
            container: The Tailscale container
            
        Returns:
            True if authorized or check failed, False if needs authorization
        """
        state_check = container.exec_run(
            "tailscale status --json",
            detach=False
        )
        if state_check.exit_code != 0:
            return True
        try:
            decoded_output = state_check.output.decode()
            state_data = json.loads(decoded_output)
            backend_state = state_data.get("BackendState", "")
            if backend_state == "NeedsMachineAuth":
                dtslogger.warning(
                    "Device needs to be authorized in the admin console."
                )
                dtslogger.info(
                    "Please approve this device at "
                    "https://login.tailscale.com/admin/machines"
                )
                return False
        except JSONDecodeError:
            pass
        return True

    @staticmethod
    def _check_device_removed(
        container: Container, 
        original_machine: str
    ) -> bool:
        """Check if device was removed from Tailscale.
        
        Args:
            container: The Tailscale container
            original_machine: Original machine identifier
            
        Returns:
            True if device was removed, False otherwise
        """
        state_check = container.exec_run(
            "tailscale status --json",
            detach=False
        )
        if state_check.exit_code != 0:
            return False
        try:
            decoded_output = state_check.output.decode()
            state_data = json.loads(decoded_output)
            self_data = state_data.get("Self", {})
            is_online = self_data.get("Online", False)
            in_network_map = self_data.get("InNetworkMap", False)
            if not is_online and in_network_map:
                last_seen = self_data.get("LastSeen", "")
                if "0001-01-01" in last_seen:
                    dtslogger.warning(
                        "Device appears to be offline and may have been "
                        "removed from Tailscale."
                    )
                    machine_arg = (
                        f" -H {original_machine}"
                        if original_machine != DEFAULT_MACHINE
                        else ""
                    )
                    dtslogger.info(
                        "If you removed this device from the admin console, "
                        "you can reconnect using "
                        f"'dts tailscale connect{machine_arg}'."
                    )
                    return True
        except JSONDecodeError:
            pass
        return False

    @staticmethod
    def _parse_status_output(output: str) -> tuple[list[list[str]], list[str]]:
        """Parse tailscale status output into data rows and other lines.
        
        Args:
            output: Raw status output string
            
        Returns:
            Tuple of (parsed data rows, other lines)
        """
        stripped_output = output.strip()
        lines = stripped_output.split("\n")
        data_lines = []
        other_lines = []
        for line in lines:
            # Check if line looks like data (starts with IP)
            if re.match(r"^\d+\.\d+\.\d+\.\d+", line):
                data_lines.append(line)
            else:
                other_lines.append(line)
        # Parse data lines into columns
        parsed_rows = []
        for data_line in data_lines:
            columns = re.split(r"  +", data_line)
            parsed_rows.append(columns)
        return parsed_rows, other_lines

    @staticmethod
    def _calculate_column_widths(
        parsed_rows: list[list[str]], 
        headers: list[str]
    ) -> list[int]:
        """Calculate column widths based on headers and data.
        
        Args:
            parsed_rows: List of parsed data rows
            headers: List of header strings
            
        Returns:
            List of column widths
        """
        if not parsed_rows:
            return [len(header) for header in headers]
        number_of_columns = max(len(row) for row in parsed_rows)
        column_widths = [len(header) for header in headers[:number_of_columns]]
        for row in parsed_rows:
            for i, column in enumerate(row):
                if i < len(column_widths):
                    column_length = len(column)
                    column_widths[i] = max(column_widths[i], column_length)
        return column_widths

    @staticmethod
    def _format_table(
        parsed_rows: list[list[str]], 
        headers: list[str], 
        column_widths: list[int]
    ) -> str:
        """Format parsed rows into a table string.
        
        Args:
            parsed_rows: List of parsed data rows
            headers: List of header strings
            column_widths: List of column widths
            
        Returns:
            Formatted table string
        """
        lines = []
        # Format header
        header_parts = []
        number_of_columns = len(column_widths)
        for i, header in enumerate(headers[:number_of_columns]):
            header_parts.append(f"{header:<{column_widths[i]}}")
        line = "  ".join(header_parts)
        lines.append(line)
        # Format data rows
        for row in parsed_rows:
            row_parts = []
            for i, column in enumerate(row):
                if i < number_of_columns:
                    row_parts.append(f"{column:<{column_widths[i]}}")
                else:
                    row_parts.append(column)
            line = "  ".join(row_parts)
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _show_status(
        container: Container,
        json_format: bool,
        machine: str
    ) -> bool:
        """Show the Tailscale status output.
        
        Args:
            container: The Tailscale container
            json_format: Whether to output in JSON format
            machine: Machine identifier
            
        Returns:
            True if status retrieved successfully, False otherwise
        """
        status_cmd = (
            "tailscale status --json" if json_format else "tailscale status"
        )
        exec_result = container.exec_run(status_cmd, detach=False)
        if exec_result.exit_code == 0:
            decoded_output = exec_result.output.decode()
            if json_format:
                print(decoded_output)
            else:
                dtslogger.info("Tailscale status:")
                parsed_rows, other_lines = DTCommand._parse_status_output(
                    decoded_output
                )
                if parsed_rows:
                    headers = [
                        "IP Address",
                        "Hostname",
                        "Owner",
                        "OS",
                        "Status"
                    ]
                    column_widths = DTCommand._calculate_column_widths(
                        parsed_rows,
                        headers
                    )
                    table = DTCommand._format_table(
                        parsed_rows,
                        headers,
                        column_widths
                    )
                    print(table)
                    # Print other lines (like health check)
                    if other_lines:
                        for line in other_lines:
                            print(line)
                else:
                    # No data lines found, print as-is
                    print(decoded_output)
            return True
        decoded_output = exec_result.output.decode()
        dtslogger.error(f"Failed to get status: {decoded_output}")
        DTCommand._handle_logged_out(decoded_output, machine)
        return False

    @staticmethod
    def _handle_logged_out(error_output: str, machine: str) -> None:
        """Handle logged out state by directing user to reconnect.
        
        Args:
            error_output: Error output from status command
            machine: Machine identifier
        """
        if (
            "Logged out" not in error_output
            and "Log in at:" not in error_output
        ):
            return
        machine_arg = (
            f" -H {machine}"
            if machine != DEFAULT_MACHINE
            else ""
        )
        dtslogger.info(
            "To reconnect to Tailscale, run 'dts tailscale "
            f"connect{machine_arg}'."
        )

    @staticmethod
    def _show_ip_address(container: Container) -> None:
        """Show the Tailscale IPv4 address.
        
        Args:
            container: The Tailscale container
        """
        try:
            exec_result = container.exec_run("tailscale ip -4", detach=False)
            if exec_result.exit_code == 0:
                decoded_output = exec_result.output.decode()
                tailscale_ip = decoded_output.strip()
                if tailscale_ip:
                    dtslogger.info(f"Tailscale IP: {tailscale_ip}")
        except Exception as error:
            dtslogger.debug(f"Could not retrieve IP: {error}")

    @staticmethod
    def _show_dns_config(container: Container) -> None:
        """Show DNS configuration instructions.
        
        Args:
            container: The Tailscale container
        """
        try:
            # Get MagicDNS info
            exec_result = container.exec_run(
                "tailscale status --json",
                detach=False
            )
            if exec_result.exit_code != 0:
                return
            decoded_output = exec_result.output.decode()
            status_data = json.loads(decoded_output)
            # Check if MagicDNS is enabled
            current_tailnet = status_data.get("CurrentTailnet", {})
            magic_dns_enabled = current_tailnet.get("MagicDNSEnabled", False)
            magic_dns_suffix = status_data.get("MagicDNSSuffix", "")
            if not magic_dns_enabled:
                dtslogger.info(
                    "MagicDNS is not enabled for the Tailscale network."
                )
                dtslogger.info(
                    "To use hostnames to connect to devices "
                    "(e.g., 'ping <hostname>'), navigate to " 
                    "https://login.tailscale.com/admin/dns and enable "
                    "MagicDNS."
                )
                return
            # MagicDNS is enabled
            dtslogger.info(
                f"MagicDNS is enabled with suffix: {magic_dns_suffix}"
            )
            dtslogger.info(
                "You can use hostnames to connect to devices "
                "(e.g., 'ping <hostname>')."
            )
        except Exception as error:
            dtslogger.debug(f"Could not retrieve DNS info: {error}")

    @staticmethod
    def _fetch_and_display_status(
        container: Container, 
        json_format: bool, 
        original_machine: str
    ) -> bool:
        """Fetch and display Tailscale status information.
        
        Args:
            container: The Tailscale container
            json_format: Whether to output in JSON format
            original_machine: Original machine identifier
            
        Returns:
            True if successful, False otherwise
        """
        # Check device authorization
        if not DTCommand._check_device_authorization(container):
            return False
        # Check if device was removed
        if DTCommand._check_device_removed(container, original_machine):
            return False
        # Show status
        if not DTCommand._show_status(container, json_format, original_machine):
            return False
        # Show IP address and DNS config (unless JSON format)
        if not json_format:
            DTCommand._show_ip_address(container)
            DTCommand._show_dns_config(container)
        return True

    @staticmethod
    def command(_: DTShell, args: list[str]) -> None:
        """Main command entry point.
        
        Args:
            _: DTShell instance (unused)
            args: Command line arguments
        """
        prog = "dts tailscale status"
        parser = ArgumentParser(prog=prog)
        parser.add_argument(
            "-H",
            "--machine",
            default=DEFAULT_MACHINE,
            help="Docker socket or hostname where Tailscale is running",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Output status in JSON format"
        )
        parsed = parser.parse_args(args)
        machine = parsed.machine
        # Connect to Docker
        client = resolve_and_connect_docker(machine)
        if not client:
            return
        # Get container
        container = DTCommand._get_container(client, machine)
        if not container:
            return
        # Check if running
        if not DTCommand._check_container_running(container):
            return
        # Get Tailscale status
        dtslogger.info("Fetching Tailscale status...")
        try:
            DTCommand._fetch_and_display_status(
                container,
                parsed.json,
                machine
            )
        except Exception as error:
            dtslogger.error(f"Failed to retrieve Tailscale status: {error}")
