import os
import platform
import subprocess
import time
import urllib.parse

from dt_shell import dtslogger
from dtproject import DTProject
from cli.command import _run_cmd

def attach_vscode_to_remote_container(host: str, container_name: str, workspace_path: str, timeout: int = 30) -> bool:
    """
    Attach VS Code to a container running on a remote SSH host.
    
    Args:
        host: SSH host (e.g., 'hostname' or 'user@hostname')
        container_name: Name or ID of the container
        workspace_path: Path inside the container to open as workspace
        timeout: Maximum time to wait for container to be ready (seconds)
        
    Returns:
        True if VS Code was successfully launched, False otherwise
    """
    try:
        # Wait for container to be in running state
        dtslogger.info(f"Waiting for container '{container_name}' to be ready on host '{host}'...")
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            # Check if container is running
            try:
                result = _run_cmd([
                    "docker", f"-H=ssh://{host}", "ps", "--filter", f"name={container_name}", 
                    "--format", "{{.Names}}\t{{.Status}}"
                ], get_output=True, suppress_errors=True)
                
                if isinstance(result, str) and result and container_name in result and "Up" in result:
                    dtslogger.info(f"Container '{container_name}' is ready!")
                    break
                    
            except Exception as e:
                dtslogger.debug(f"Container check failed: {e}")
                
            time.sleep(1)
        else:
            dtslogger.error(f"Container '{container_name}' did not become ready within {timeout} seconds")
            return False
        
        # Get the full container ID if we have a name
        try:
            container_id_result = _run_cmd([
                "docker", f"-H=ssh://{host}", "ps", "--filter", f"name={container_name}", 
                "--format", "{{.ID}}", "--no-trunc"
            ], get_output=True, suppress_errors=True)
            
            if isinstance(container_id_result, str) and container_id_result.strip():
                container_id = container_id_result.strip()
            else:
                dtslogger.warning(f"Could not resolve container ID for '{container_name}', using name")
                container_id = container_name
        except Exception:
            container_id = container_name
        
        # Try different approaches to open VS Code with the remote container
        dtslogger.info(f"Opening VS Code in remote container on {host} at {workspace_path}...")
        dtslogger.debug(f"Container ID: {container_id}")
        
        # Try using VS Code CLI with proper URI format
        try:
            # Check if 'code' command is available
            version_result = _run_cmd(["code", "--version"], get_output=True, suppress_errors=True)
            code_cli_found = isinstance(version_result, str) and version_result.strip()
            
            if code_cli_found:
                # Construct proper VS Code remote container URI for SSH host
                # Format: vscode://vscode-remote/attached-container+<hex_encoded_json><folder_path>
                import json
                
                try:
                    # Create the JSON data structure
                    container_data = {
                        "settings": {"host": f"ssh://{host}"},
                        "containerName": container_id
                    }
                    
                    # Convert JSON to string and then to hex encoding
                    json_str = json.dumps(container_data)
                    hex_encoded = ''.join(f'{ord(c):02x}' for c in json_str)
                    
                    # Construct the URI with hex-encoded JSON and workspace path
                    vscode_uri = f"vscode://vscode-remote/attached-container+{hex_encoded}{workspace_path}"
                    
                    dtslogger.debug(f"Trying VS Code URI: {vscode_uri}")
                    _run_cmd(["code", "--folder-uri", vscode_uri], suppress_errors=True)
                    dtslogger.info("VS Code opened successfully")
                    return True
                    
                except Exception as e:
                    dtslogger.debug(f"VS Code URI format failed: {e}")
            
        except Exception as e:
            dtslogger.debug(f"VS Code CLI check failed: {e}")
        
        if not code_cli_found:
            dtslogger.warning("VS Code CLI 'code' not found in PATH. Trying OS URL handler...")
        
        # Fallback to OS URL handler
        try:
            system = platform.system().lower()
            
            if system == "darwin":  # macOS
                _run_cmd(["open", vscode_uri], suppress_errors=True)
            elif system == "linux":
                _run_cmd(["xdg-open", vscode_uri], suppress_errors=True)
            elif system == "windows":
                _run_cmd(["start", vscode_uri], shell=True, suppress_errors=True)
            else:
                dtslogger.warning(f"Unsupported platform: {system}")
                return False
                
            dtslogger.info("VS Code opened successfully via OS URL handler")
            return True
            
        except Exception as e:
            dtslogger.error(f"Failed to open VS Code via URL handler: {e}")
            
        # If we reach here, both methods failed
        dtslogger.error(
            f"Could not open VS Code. Please ensure:\n"
            f"1. VS Code is installed with the Dev Containers extension\n"
            f"2. The 'code' command is in your PATH, or\n"
            f"3. Your system supports opening vscode:// URIs\n\n"
            f"You can manually open VS Code and use this URI:\n{vscode_uri}"
        )
        return False
        
    except Exception as e:
        dtslogger.error(f"Unexpected error while attaching VS Code: {e}")
        return False


def handle_vscode_attachment(parsed, container_name: str, project: DTProject) -> None:
    """
    Handle VS Code attachment logic.
    
    Args:
        parsed: Parsed command arguments
        container_name: Name of the container to attach to
        project: DTProject instance
    """
    # Only attach VS Code if we're running on a remote host
    from utils.docker_utils import DEFAULT_MACHINE
    
    if parsed.machine == DEFAULT_MACHINE:
        dtslogger.warning(
            "The --code flag is intended for use with remote SSH hosts (-H/--machine). "
            "For local containers, you can use VS Code's 'Dev Containers: Attach to Running Container' command directly."
        )
        return
    
    # Extract SSH host from machine parameter
    # Handle formats like "ssh://user@host", "user@host", "hostname"
    ssh_host = parsed.machine
    if ssh_host.startswith("ssh://"):
        ssh_host = ssh_host[6:]  # Remove "ssh://" prefix
    
    # Determine workspace path inside container
    # Use the sync destination path if syncing is enabled, otherwise use default project paths
    if getattr(parsed, 'sync', False):
        workspace_path = os.path.join(parsed.sync_destination, project.name)
    else:
        # Use the project's code paths to determine the workspace
        local_paths, remote_paths = project.code_paths("/code")
        if remote_paths:
            workspace_path = remote_paths[0]  # Use the first remote path as workspace
        else:
            workspace_path = f"/code/{project.name}"  # Default fallback
    
    # Attempt to attach VS Code
    success = attach_vscode_to_remote_container(ssh_host, container_name, workspace_path)
    
    if not success:
        dtslogger.info(
            f"VS Code attachment failed. You can manually attach VS Code using:\n"
            f"1. Open VS Code\n"
            f"2. Press Ctrl+Shift+P (Cmd+Shift+P on Mac)\n" 
            f"3. Select 'Dev Containers: Attach to Running Container'\n"
            f"4. Choose the SSH host '{ssh_host}'\n"
            f"5. Select container '{container_name}'\n"
            f"6. Open folder '{workspace_path}'"
        )
