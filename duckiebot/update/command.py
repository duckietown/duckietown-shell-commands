import argparse
import copy
import os
import shutil
import socket as _socket
import subprocess
import time
import urllib.request
from typing import Optional, Dict
from urllib.parse import urlparse as _urlparse

import questionary
from docker import DockerClient
from docker.errors import NotFound

from dt_shell import DTCommandAbs, DTShell, dtslogger
from dt_shell.profile import DockerCredentials
from utils.docker_utils import (
    get_client_OLD,
    get_endpoint_architecture,
    get_registry_to_use,
    login_client_OLD,
    pull_image_OLD,
)
from utils.exceptions import UserAborted
from utils.kvstore_utils import KVStore
from utils.networking_utils import best_host_for_robot
from utils.robot_utils import log_event_on_robot

WHEN_NO_DISTRO = "ente"
DEFAULT_STACKS = "robot/basics,duckietown/{robot_type},ros{ros_version}/{robot_type}"
OTHER_IMAGES_TO_UPDATE = [
    # TODO: this is disabled for now, too big for the SD card
    # "{registry}/duckietown/dt-gui-tools:{distro}-{arch}",
    # "{registry}/duckietown/dt-core:{distro}-{arch}",
    # "{registry}/duckietown/dt-duckiebot-fifos-bridge:{distro}-{arch}",
    # "{registry}/duckietown/challenge-aido_lf-baseline-duckietown:{distro}-{arch}",
    # "{registry}/duckietown/challenge-aido_lf-template-ros:{distro}-{arch}",
]

STACKS_TO_LOAD = {
    "basics": "robot/basics",
    "duckietown": "duckietown/{robot_type}",
    "ros{ros_version}": "ros{ros_version}/{robot_type}",
}

ROBOT_PROXY_DROP_IN = "/etc/systemd/system/docker.service.d/dts-proxy.conf"
ROBOT_PROXY_SETUP_SCRIPT = "/usr/local/bin/dts-proxy-setup"
ROBOT_PROXY_ENV_FILE = "/run/dts-proxy.env"
SOCAT_LAN_PORT = 17897
DOCKER_RESTART_TIMEOUT = 60


def _get_robot_image(client: DockerClient) -> str:
    """Return a tag from an image already cached on the robot.

    Using a pre-cached image avoids a Docker Hub pull which may not be reachable.
    Falls back to 'alpine:3.23.3' in the unlikely case no images exist yet.
    """
    try:
        for img in client.images.list():
            if img.tags:
                return img.tags[0]
    except Exception:
        pass
    return "alpine:3.23.3"


def _wait_for_docker(hostname: str, timeout: int = DOCKER_RESTART_TIMEOUT) -> None:
    """Block until the robot's Docker daemon responds on its TCP endpoint after a restart.

    Probes /version with a fresh connection each time — this is identical to what
    get_client_OLD does, so success here guarantees the subsequent client creation
    will not see a 'Connection refused'.
    """
    url = f"http://{hostname}:2375/version"
    for _ in range(timeout):
        time.sleep(1)
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except Exception:
            pass
    raise TimeoutError(f"Robot Docker daemon did not come back up within {timeout} seconds after restart.")


def _setup_robot_proxy(client: DockerClient, proxy_url: str, no_proxy: str, run_image: str) -> None:
    """Configure the robot's Docker daemon to pull through the given HTTP proxy."""
    dtslogger.info(f"Configuring robot Docker daemon to use proxy: {proxy_url}")

    # Parse host and port for the connectivity-check script.
    _parsed_proxy = _urlparse(proxy_url)
    proxy_host = _parsed_proxy.hostname or ""
    proxy_port_str = str(_parsed_proxy.port or 80)

    # Runtime env file written immediately so the very next Docker restart picks up the
    # proxy. /run/ is a tmpfs on Linux and is cleared on every reboot, so a stale drop-in
    # left behind after a reboot is harmless — the EnvironmentFile= directive will find no
    # file and Docker starts without any proxy configured.
    env_file_content = (
        f"HTTP_PROXY={proxy_url}\n"
        f"HTTPS_PROXY={proxy_url}\n"
        f"NO_PROXY=localhost,127.0.0.1,{no_proxy}\n"
    )

    # Check script run by ExecStartPre= on every Docker restart: recreates
    # /run/dts-proxy.env only if the proxy host is still reachable; otherwise clears it.
    # This makes leftover configuration safe even without a reboot.
    setup_script_content = (
        "#!/bin/sh\n"
        f'if python3 -c "import socket; socket.create_connection((\'{proxy_host}\', {proxy_port_str}), timeout=2).close()" 2>/dev/null; then\n'
        f'    printf "HTTP_PROXY={proxy_url}\\nHTTPS_PROXY={proxy_url}\\nNO_PROXY=localhost,127.0.0.1,{no_proxy}\\n" > /run/dts-proxy.env\n'
        "else\n"
        "    : > /run/dts-proxy.env\n"
        "fi\n"
    )

    # Drop-in: ExecStartPre= conditionally populates the env file before the daemon reads
    # it. Both use the '-' prefix to tolerate absence/failure gracefully.
    drop_in_content = (
        "[Service]\n"
        f"ExecStartPre=-{ROBOT_PROXY_SETUP_SCRIPT}\n"
        "EnvironmentFile=-/run/dts-proxy.env\n"
    )

    drop_in_dir = os.path.dirname(ROBOT_PROXY_DROP_IN)
    setup_script_dir = os.path.dirname(ROBOT_PROXY_SETUP_SCRIPT)

    # Step 1: write all files via python3 in a privileged container.
    # repr() handles all quoting and escaping automatically.
    write_code = (
        "import os; "
        f"os.makedirs({repr('/host' + drop_in_dir)}, exist_ok=True); "
        f"os.makedirs({repr('/host' + setup_script_dir)}, exist_ok=True); "
        f"f=open({repr('/host' + ROBOT_PROXY_ENV_FILE)}, 'w'); f.write({repr(env_file_content)}); f.close(); "
        f"f=open({repr('/host' + ROBOT_PROXY_SETUP_SCRIPT)}, 'w'); f.write({repr(setup_script_content)}); f.close(); "
        f"os.chmod({repr('/host' + ROBOT_PROXY_SETUP_SCRIPT)}, 0o755); "
        f"f=open({repr('/host' + ROBOT_PROXY_DROP_IN)}, 'w'); f.write({repr(drop_in_content)}); f.close()"
    )
    client.containers.run(
        image=run_image,
        entrypoint=["python3", "-c"],
        command=[write_code],
        volumes={"/": {"bind": "/host", "mode": "rw"}},
        pid_mode="host",
        privileged=True,
        remove=True,
        detach=False,
    )
    # Step 2: reload systemd and restart Docker in a detached container.
    # The Docker restart will kill this container — that is expected and not an error.
    restart_script = (
        "nsenter -t 1 -m -u -i -n -p -- systemctl daemon-reload && "
        "nsenter -t 1 -m -u -i -n -p -- systemctl restart docker"
    )
    try:
        client.containers.run(
            image=run_image,
            entrypoint=["sh", "-c"],
            command=[restart_script],
            pid_mode="host",
            privileged=True,
            detach=True,
        )
    except Exception:
        # Docker restart kills the container connection — this is expected
        # The caller is responsible for waiting until the daemon is back up.
        pass


def _restore_robot_proxy(client: DockerClient, run_image: str) -> None:
    """Remove the proxy drop-in from the robot and restart its Docker daemon."""
    dtslogger.info("Restoring robot Docker daemon configuration...")
    # Step 1: remove the proxy drop-in, check script, and env file
    delete_script = f"rm -f /host{ROBOT_PROXY_DROP_IN} /host{ROBOT_PROXY_SETUP_SCRIPT} /host{ROBOT_PROXY_ENV_FILE}"
    client.containers.run(
        image=run_image,
        entrypoint=["sh", "-c"],
        command=[delete_script],
        volumes={"/": {"bind": "/host", "mode": "rw"}},
        pid_mode="host",
        privileged=True,
        remove=True,
        detach=False,
    )
    # Step 2: reload systemd and restart Docker in a detached container.
    restart_script = (
        "nsenter -t 1 -m -u -i -n -p -- systemctl daemon-reload && "
        "nsenter -t 1 -m -u -i -n -p -- systemctl restart docker"
    )
    try:
        client.containers.run(
            image=run_image,
            entrypoint=["sh", "-c"],
            command=[restart_script],
            pid_mode="host",
            privileged=True,
            detach=True,
        )
    except Exception:
        # Docker restart kills the container connection — this is expected
        # The caller is responsible for waiting until the daemon is back up.
        pass


def _detect_local_proxy_port() -> Optional[int]:
    """Return the port of a local HTTP proxy from env vars, or None if not set."""
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        val = os.environ.get(var, "")
        if not val:
            continue
        try:
            parsed = _urlparse(val)
            if parsed.hostname == "127.0.0.1" and parsed.port:
                dtslogger.info(f"Detected proxy from env {var}: port {parsed.port}")
                return parsed.port
        except Exception:
            pass
    return None


_socat_process = None


def _ensure_socat_forwarder(local_ip: str, lan_port: int, proxy_port: int) -> bool:
    """Ensure socat is forwarding local_ip:lan_port -> 127.0.0.1:proxy_port.

    Starts socat in the background if the port is not already bound.
    Returns True if the forwarder is available after the call.
    """
    global _socat_process
    # Already listening?
    s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    s.settimeout(1)
    try:
        s.connect((local_ip, lan_port))
        s.close()
        dtslogger.info(f"Socat forwarder already running on {local_ip}:{lan_port}.")
        return True
    except OSError:
        pass
    if not shutil.which("socat"):
        dtslogger.error("socat is not installed. Install it with: sudo apt-get install -y socat")
        return False
    dtslogger.info(f"Starting socat forwarder {local_ip}:{lan_port} -> 127.0.0.1:{proxy_port} ...")
    _socat_process = subprocess.Popen(
        ["socat", f"TCP-LISTEN:{lan_port},bind={local_ip},fork,reuseaddr", f"TCP:127.0.0.1:{proxy_port}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1)
    s2 = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    s2.settimeout(2)
    try:
        s2.connect((local_ip, lan_port))
        s2.close()
        dtslogger.info("Socat forwarder started.")
        return True
    except OSError:
        dtslogger.error(f"Socat forwarder failed to start on {local_ip}:{lan_port}.")
        if _socat_process is not None:
            _socat_process.terminate()
            _socat_process = None
        return False


def _config_node_directory_exists(client: DockerClient, run_image: str) -> bool:
    try:
        # Check if the /data/config/node directory exists
        client.containers.run(
            image=run_image,
            command=["test", "-d", "/data/config/node"],
            volumes={
                "/data": {
                    "bind": "/data",
                    "mode": "ro"
                }
            },
            remove=True,
            detach=False
        )
    except Exception:
        return False
    return True

def _delete_config_node_directory(client: DockerClient, run_image: str) -> None:
    dtslogger.info("Deleting node configuration directory...")
    try:
        # Delete the /data/config/node directory
        client.containers.run(
            image=run_image,
            command=["rm", "-rf", "/data/config/node"],
            volumes={
                "/data": {
                    "bind": "/data",
                    "mode": "rw"
                }
            },
            remove=True,
            detach=False
        )
        dtslogger.info("Successfully deleted node configuration directory.")
    except Exception as e:
        dtslogger.warning(f"Error deleting node configuration directory: {e}")


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts duckiebot update"
        parser = argparse.ArgumentParser(prog=prog)
        # define arguments
        parser.add_argument(
            "-k", "--no-clean", action="store_true", default=False, help="Do NOT perform a clean step"
        )
        parser.add_argument(
            "-n", "--no-pull", action="store_true", default=False, help="Do NOT pull new images, just heal the stacks"
        )
        parser.add_argument(
            "-d", "--deep-clean", action="store_true", default=False, help="Deep cleans the SD card before updating"
        )
        parser.add_argument(
            "-f", "--force", action="store_true", default=False, help="Force the operation when not recommended"
        )
        parser.add_argument(
            "--distro", type=str, default=WHEN_NO_DISTRO, help="Specify the distro to use for the update (default: daffy)"
        )
        parser.add_argument(
            "-t", "--robot-type", type=str, default=None, help="Force using a specific robot type (the -f flag MUST also be selected)"
        )
        parser.add_argument(
            "--robot-hardware", type=str, default=None, help="Force using a specific robot hardware (the -f flag MUST also be selected)"
        )
        parser.add_argument(
            "--reset-node-configs", action="store_true", default=False, help="Reset node configurations after next boot"
        )

        parser.add_argument("robot", nargs=1, help="Name of the Robot to update")
        # parse arguments
        parsed = parser.parse_args(args)
        # sanitize arguments
        parsed.robot = parsed.robot[0]
        registry_to_use = get_registry_to_use()
        distro: str = shell.profile.distro.name
        stacks: Dict[str, str] = copy.deepcopy(STACKS_TO_LOAD)

        # resolve robot hostname
        robot: str = parsed.robot
        hostname: str = best_host_for_robot(robot)

        # open KVStore
        kv: KVStore = KVStore(robot)

        # get the robot type
        rtype: Optional[str]
        robot_hardware: Optional[str]
        if kv.is_available():
            rtype = kv.get(str, "robot/type", None)
            robot_hardware = kv.get(str, "robot/hardware", None)
        else:
            robot_hardware = None
            rtype = None

        if rtype is None and parsed.robot_type is None:
            dtslogger.warning(f"Could not get the robot type from robot '{robot}'")
            rtype = questionary.select(
                "Select robot type:", choices=["duckiebot", "duckiedrone", "traffic_light"]
            ).unsafe_ask()
            if rtype is None:
                raise UserAborted()
            dtslogger.info(f"Declared robot type: {rtype}")
        elif parsed.force and parsed.robot_type is not None:
            rtype = parsed.robot_type
        else:
            dtslogger.info(f"Detected robot type: {rtype}")
            
        assert rtype is not None

        if robot_hardware is None and parsed.robot_hardware is None:
            dtslogger.warning(f"Could not get the robot hardware from robot '{robot}'")
            robot_hardware = questionary.select(
                "Enter robot hardware:",
                choices=["jetson_orin_nano", "jetson_nano", "raspberry_pi_64", "raspberry_pi", "virtual"],
            ).unsafe_ask()
            if not robot_hardware:
                raise UserAborted()
            dtslogger.info(f"Declared robot hardware: {robot_hardware}")
        elif parsed.force and parsed.robot_hardware is not None:
            robot_hardware = parsed.robot_hardware
        else:
            dtslogger.info(f"Detected robot hardware: {robot_hardware}")

        # replace the placeholder in the stacks
        resolved_stacks: Dict[str, str] = {}
        
        for project, stack_fmt in stacks.items():
            ros_version = "2" if rtype == "duckiedrone" else "1"
            project = project.format(ros_version=ros_version)
            stack_fmt = stack_fmt.format(robot_type=rtype, ros_version=ros_version)
            resolved_stacks[project] = stack_fmt
        stacks = resolved_stacks

        # check whether the robot is using a different distro
        rdistro: Optional[str]
        if kv.is_available():
            rdistro = kv.get(str, "robot/distro", distro)
        else:
            dtslogger.warning(f"Could not get the distro from robot '{robot}'. Assuming '{distro}'")
            rdistro = distro

        if rdistro is not None:
            dtslogger.info(f"Detected distro '{rdistro}' on robot '{robot}'")
            if rdistro != distro:
                dtslogger.warning(
                    f"The robot '{robot}' is using the distro '{rdistro}' while your shell is set on '{distro}'. "
                    f"We do not recommend updating the robot with a different distro."
                )
                if parsed.force:
                    dtslogger.warning("Forced!")
                    # take stack down
                    for project, stack in stacks.items():
                        success = shell.include.stack.down.command(
                            shell,
                            ["--machine", robot, stack.strip()],
                        )
                        if not success:
                            return
                else:
                    dtslogger.warning("You can use the -f/--force flag to force the operation "
                                      "(if you know what you are doing).")
                    dtslogger.warning("Aborting.")
                    return

        # clean duckiebot and offer user abort option
        if parsed.deep_clean:
            try:
                shell.include.duckiebot.clean.command(shell, [robot, "--all"])
            except UserAborted as e:
                dtslogger.info(e)
                return

        # compile image names
        arch = get_endpoint_architecture(hostname)
        images = [
            img.format(registry=registry_to_use, distro=distro, arch=arch) for img in OTHER_IMAGES_TO_UPDATE
        ]
        client = get_client_OLD(hostname)
        run_image: str = _get_robot_image(client)
        credentials: DockerCredentials = shell.profile.secrets.docker_credentials

        # If HTTPS_PROXY / HTTP_PROXY is set, forward the proxy to the robot via socat
        # so its Docker daemon can pull images from docker.io through it.
        robot_proxy_configured: bool = False
        try:
            s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
            s.connect((_socket.gethostbyname(hostname), 80))
            local_ip = s.getsockname()[0]
            s.close()
            proxy_port = _detect_local_proxy_port()
            if proxy_port is not None:
                _ensure_socat_forwarder(local_ip, SOCAT_LAN_PORT, proxy_port)
                proxy_url = f"http://{local_ip}:{SOCAT_LAN_PORT}"
                _setup_robot_proxy(client, proxy_url, hostname, run_image)
                _wait_for_docker(hostname)
                client = get_client_OLD(hostname)
                robot_proxy_configured = True
                dtslogger.info("Robot Docker daemon proxy configured; pulls will route through the proxy.")
        except Exception as e:
            dtslogger.warning(f"Could not auto-configure robot proxy: {e}. Continuing anyway.")

        def _restore_proxy_if_needed():
            if not robot_proxy_configured:
                return
            last_restore_error = None
            for _attempt in range(3):
                try:
                    if _attempt > 0:
                        dtslogger.info(f"Retrying restore (attempt {_attempt + 1}/3)...")
                    restore_client = get_client_OLD(hostname)
                    _restore_robot_proxy(restore_client, run_image)
                    _wait_for_docker(hostname)
                    dtslogger.info("Robot Docker daemon configuration restored.")
                    last_restore_error = None
                    break
                except Exception as e:
                    last_restore_error = e
            if last_restore_error is not None:
                dtslogger.warning(
                    f"Could not restore robot Docker daemon configuration: {last_restore_error}\n"
                    f"To restore manually, SSH into the robot and run:\n"
                    f"  sudo rm -f {ROBOT_PROXY_DROP_IN} {ROBOT_PROXY_SETUP_SCRIPT}\n"
                    f"  sudo systemctl daemon-reload && sudo systemctl restart docker"
                )

        try:
            login_client_OLD(client, credentials, registry_to_use, raise_on_error=False)
            # it looks like the update is going to happen, mark the event
            log_event_on_robot(robot, "duckiebot/update")

            if _config_node_directory_exists(client, run_image):
                if parsed.reset_node_configs:
                    _delete_config_node_directory(client, run_image)
                else:
                    choice = input(
                        "Reset node configurations after next boot? [Y/n]: "
                    )
                    if choice.lower() != "n":
                        _delete_config_node_directory(client, run_image)

            # stack/up options

            # `--remove-orphans` removes containers a stack no longer declares; otherwise,
            # they can keep restarting on already-deployed robots.
            stack_up_options = ["--machine", robot, "--detach", "--remove-orphans"]
            if not parsed.no_pull:
                stack_up_options.append("--pull")

            # call `stack up` command for all stacks to update
            for project, stack in stacks.items():
                dtslogger.info(f"Updating stack `{stack}`...")
                success = shell.include.stack.up.command(shell, stack_up_options + [stack.strip(),])
                if not success:
                    return

            # update non-active images
            if not parsed.no_pull:
                for image in images:
                    dtslogger.info(f"Pulling image `{image}`...")
                    try:
                        pull_image_OLD(image, client)
                    except NotFound:
                        dtslogger.error(f"Image '{image}' not found on registry '{registry_to_use}'. Aborting.")
                        return

            # set the distro on the robot
            if kv.is_available():
                if distro != rdistro:
                    dtslogger.info(f"Setting the distro '{distro}' on robot '{robot}'")
                kv.set("robot/distro", distro, persist=True, fail_quietly=True)
            else:
                dtslogger.warning(f"Could not set the distro '{distro}' on robot '{robot}'")

            # clean duckiebot (again)
            if not parsed.no_clean:
                shell.include.duckiebot.clean.command(shell, [robot, "--all", "--yes", "--untagged"])

        except KeyboardInterrupt:
            dtslogger.warning("Update interrupted by user.")
        finally:
            _restore_proxy_if_needed()
            if _socat_process is not None and _socat_process.poll() is None:
                _socat_process.terminate()

        dtslogger.info("Update completed!")
