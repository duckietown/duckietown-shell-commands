import argparse
import requests

from dt_shell import DTCommandAbs, dtslogger, DTShell
from utils.docker_utils import DEFAULT_MACHINE, get_client

TOKEN_URL = (
    "https://auth.docker.io/token?" "service=registry.docker.io&scope=repository:ratelimitpreview/test:pull"
)
LIMITS_URL = "https://registry-1.docker.io/v2/ratelimitpreview/test/manifests/latest"


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
        # parse arguments
        parsed = parser.parse_args(args)
        if parsed.machine is not None:
            parsed.machine = f"{parsed.machine.rstrip('.local')}.local"
        else:
            parsed.machine = DEFAULT_MACHINE

        # request token
        try:
            dtslogger.info("Requesting a token to DockerHub...")
            res = requests.get(TOKEN_URL).json()
            dtslogger.info("Token obtained successfully!")
        except BaseException:
            dtslogger.error("An error occurred while contacting the Docker Hub API. Retry.")
            return

        # get token
        token = res["token"]

        # spin up a docker client
        docker = get_client(parsed.machine)

        # run curl on the docker endpoint
        command = f'--head -H "Authorization: Bearer {token}" {LIMITS_URL}'
        dtslogger.info("Fetching current limits...")
        out = docker.containers.run(
            image="curlimages/curl:7.73.0",
            command=command,
            detach=False,
            stdout=True,
            stderr=False,
            remove=True,
        )

        # show only relevant lines
        print("-" * 24)
        for line in out.split(b"\n"):
            if line.startswith(b"RateLimit"):
                line = line.decode("utf-8").strip()
                if ";" in line:
                    line = line[: line.index(";")]
                print(line)
        print("-" * 24)

        # ---
        dtslogger.info("Done!")
