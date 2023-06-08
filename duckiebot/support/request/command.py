import argparse
import atexit
import json

import requests
from dt_shell import DTCommandAbs, DTShell, dtslogger, UserError
from utils.docker_utils import (
    get_remote_client,
    pull_if_not_exist,
    pull_image,
    remove_if_running)
from utils.exceptions import ShellNeedsUpdate
from utils.misc_utils import sanitize_hostname
from utils.networking_utils import get_duckiebot_ip

# NOTE: this is to avoid breaking the user workspace
try:
    import dockertown
except ImportError:
    raise ShellNeedsUpdate("5.4.0+")
# NOTE: this is to avoid breaking the user workspace


BASE_IMAGE = "cloudflare/cloudflared"
VERSION = "latest"
ARCH = "arm64"
API_CREATE_URL = "https://staging-hub.duckietown.com/api/v1/tunnel/create"


usage = """

## Basic usage
    This command requests direct support for your Duckiebot from the Duckietown technical team .

"""


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        # Configure args
        prog = "dts duckiebot support request"
        parser = argparse.ArgumentParser(prog=prog, usage=usage)

        parser.add_argument(
            "robot",
            nargs=1,
            help="Name of the robot to support")

        parser.add_argument(
            "--pull",
            action="store_true",
            default=False,
            help="Update the support image"
        )

        parser.add_argument(
            "--network",
            default="host",
            help="Name of the network to connect the container to"
        )

        parser.add_argument(
            "--detach",
            "-d",
            action="store_true",
            default=False,
            help="Detach from container",
        )

        # Get pre-parsed or parse arguments
        parsed = kwargs.get("parsed", None)
        if not parsed:
            parsed, _ = parser.parse_known_args(args=args)
        parsed.robot = parsed.robot[0]
        robot_hostname = sanitize_hostname(parsed.robot)
        robot_ip = get_duckiebot_ip(parsed.robot)
        dtslogger.debug(f"Found {robot_hostname} at {robot_ip}")

        # Set up the tunnel
        robot_id: str = get_robot_id(robot_hostname)
        dt_token = shell.shell_config.token_dt1
        if dt_token is None:
            raise UserError("Please set your Duckietown token using the command 'dts tok set'")
        cred: dict = create_cloudflare_tunnel(robot_id, dt_token)
        tunnel_token: str = cred["tunnel"]["token"]
        tunnel_dns: str = cred["dns"][0]
        tunnel_name: str = cred["tunnel"]["credentials_file"]["TunnelName"]

        # Set up docker
        robot_client = get_remote_client(robot_ip)
        tunneling_image = f"{BASE_IMAGE}:{VERSION}-{ARCH}"

        # Create the container
        container_name: str = "device-support"
        remove_if_running(robot_client, container_name)
        pull_if_not_exist(robot_client, tunneling_image)
        if parsed.pull:
            pull_image(tunneling_image, robot_client)

        args = {
            "image": tunneling_image,
            "name": container_name,
            "detach": True,
            "network_mode": parsed.network,
            "command": f"tunnel --url ssh://localhost:22 run --token {tunnel_token} {tunnel_name}"
        }
        dtslogger.info(f"Starting the support container '{container_name}' on {robot_hostname} ...")
        dtslogger.debug(
            f"Calling docker.run with arguments:\n" f"{json.dumps(args, indent=4, sort_keys=True)}\n"
        )

        # Give final instructions
        bar: str = "=" * len(tunnel_dns)
        spc: str = " " * len(tunnel_dns)
        dtslogger.info(
            f"\n\n"
            f"====================={bar}===========================================\n"
            f"|                    {spc}                                          |\n"
            f"|     Your Duckiebot is now starting a support tunnel.{spc}         |\n"
            f"|     Leave this command running until debugging is finished.{spc}  |\n"
            f"|                    {spc}                                          |\n"
            f"|        > Support ID - {tunnel_dns}                                       |\n"
            f"|                    {spc}                                          |\n"
            f"|     Press Enter when you are ready to exit.{spc}                  |\n"                              
            f"|                    {spc}                                          |\n"
            f"====================={bar}===========================================\n"
        )

        # Create and handle the support container
        support_container = robot_client.containers.run(**args)
        atexit.register(_shutdown_handler, container=support_container)
        input("")


def create_cloudflare_tunnel(robot_id: str, dt_token: str) -> dict:
    creation_url: str = f"{API_CREATE_URL}?robot={robot_id}&service=ssh"
    try:
        cred_response = requests.get(creation_url, headers={'Authorization': f'Token {dt_token}'})
        cred = cred_response.json()
        dtslogger.debug(f"Tunnel endpoint returned: \n\n {cred}")

        return cred["result"]

    except ConnectionError as e:
        dtslogger.error(f"There was a problem reaching the DT API: {e}")


def get_robot_id(hostname: str) -> str:
    robot_id_url = f"http://{hostname}/files/data/stats/MAC/eth0"
    try:
        id_response = requests.get(robot_id_url)
        robot_id = id_response.text.replace(":", "").strip()
        dtslogger.debug(f"Robot ID found: \n\n {id_response.text}")

        return robot_id

    except ConnectionError as e:
        dtslogger.error(f"There was a problem reaching the robot: {e}")


def _shutdown_handler(container):
    container.kill()
