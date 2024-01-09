import argparse
import atexit
import json

import requests
from dt_shell import DTCommandAbs, DTShell, dtslogger
from utils.docker_utils import get_remote_client, pull_if_not_exist, pull_image, remove_if_running
from dt_shell.exceptions import ShellNeedsUpdate
from utils.misc_utils import sanitize_hostname, pretty_json
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
API_CREATE_URL = "https://hub.duckietown.com/api/v1/tunnel/create"


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

        parser.add_argument("robot", nargs=1, help="Name of the robot to support")

        parser.add_argument("--pull", action="store_true", default=False, help="Update the support image")

        parser.add_argument(
            "--network", default="host", help="Name of the network to connect the container to"
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
        dt_token: str = shell.profile.secrets.dt_token
        cred: dict = create_cloudflare_tunnel(robot_id, dt_token)

        tunnel_token: str = "NOTSET"
        tunnel_dns: str = "NOTSET"
        tunnel_name: str = "NOTSET"

        try:
            tunnel_token = cred["tunnel"]["token"]
            tunnel_dns = cred["dns"][0]
            tunnel_name = cred["tunnel"]["credentials_file"]["TunnelName"]
        except Exception as e:
            dtslogger.error("An error occurred while parsing the response from the Duckietown API")
            dtslogger.debug(f"Error:\n{str(e)}")
            dtslogger.debug(f"API response:\n{pretty_json(cred, indent=4)}")
            exit(1)

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
            "command": f"tunnel --url ssh://localhost:22 run --token {tunnel_token} {tunnel_name}",
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
        tunnel_response = requests.get(creation_url, headers={"Authorization": f"Token {dt_token}"})
        tunnel = tunnel_response.json()
        dtslogger.debug(f"Tunnel endpoint returned:\n{pretty_json(tunnel, indent=4)}")

        # TODO: update API endpoint to return code outside of "errors"
        # if not tunnel["success"]:
        #

        return tunnel["result"]

    except ConnectionError as e:
        dtslogger.error(f"There was a problem reaching the Duckietown API: {e}")


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
