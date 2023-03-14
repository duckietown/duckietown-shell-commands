import argparse
import requests

from dt_shell import DTCommandAbs, dtslogger, DTShell
from utils.docker_utils import DEFAULT_MACHINE, get_client
from utils.misc_utils import pretty_json

TOKEN_URL = "https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repository}:pull"
LIMITS_URL = "https://registry-1.docker.io/v2/{repository}/manifests/{tag}"
DEFAULT_IMAGE = "ratelimitpreview/test:latest"


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts docker limits"
        parser = argparse.ArgumentParser(prog=prog)
        # define arguments
        parser.add_argument(
            "-H",
            "--machine",
            default=None,
            type=str,
            help="Docker engine from where to check the Docker Hub pull limits",
        )
        parser.add_argument(
            "-u",
            "--username",
            default=None,
            type=str,
            help="Username to check the limits for",
        )
        parser.add_argument(
            "-p",
            "--password",
            default=None,
            type=str,
            help="Password for the given username",
        )
        parser.add_argument(
            "-i",
            "--image",
            default=DEFAULT_IMAGE,
            type=str,
            help="Image to get the manifest for",
        )

        # parse arguments
        parsed = parser.parse_args(args)
        if parsed.machine is not None:
            parsed.machine = f"{parsed.machine.rstrip('.local')}.local"
        else:
            parsed.machine = DEFAULT_MACHINE

        # check for consistency
        if parsed.username and not parsed.password:
            dtslogger.error("You must specify a --password together with -u/--username")
            return False

        # authentication (if any)
        auth = None
        if parsed.username:
            auth = (parsed.username, parsed.password)

        # image to use
        repository, tag, *_ = parsed.image.split(":") + ["latest"]
        dtslogger.debug(f"Using image: {repository}:{tag}")

        # request token
        token_url: str = TOKEN_URL.format(repository=repository)
        dtslogger.debug(f"Using auth URL: {token_url}")
        try:
            dtslogger.info("Requesting a token to DockerHub...")
            res = requests.get(token_url, auth=auth).json()
            dtslogger.info("Token obtained successfully!")
        except BaseException:
            dtslogger.error("An error occurred while contacting the Docker Hub API. Retry.")
            return False

        # get token
        token = res["token"]
        dtslogger.debug(f"Token: {token}")

        # spin up a docker client
        docker = get_client(parsed.machine)

        # compile limits url
        limits_url: str = LIMITS_URL.format(repository=repository, tag=tag)
        dtslogger.debug(f"Using manifest URL: {limits_url}")

        # run curl on the docker endpoint
        command = f'--head -H "Authorization: Bearer {token}" {limits_url}'
        dtslogger.info("Fetching current limits...")
        args = {
            "image": "curlimages/curl:7.73.0",
            "command": command,
            "detach": False,
            "stdout": True,
            "stderr": False,
            "remove": True,
        }
        dtslogger.debug(f"Running container with arguments: {pretty_json(args, indent=4)}")
        out = docker.containers.run(**args)

        print(out)

        # show only relevant lines
        print("-" * 24)
        for line in out.split(b"\n"):
            if line.lower().startswith(b"ratelimit"):
                line = line.decode("utf-8").strip()
                limit, *_ = line.split(";")
                print(line)
        print("-" * 24)

        # ---
        dtslogger.info("Done!")
