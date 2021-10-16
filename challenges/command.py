import argparse
import getpass
import json
import os
import random
from datetime import datetime
from typing import Dict, List

from dt_shell import check_package_version, DTCommandAbs, DTShell, UserError, dtslogger
from dt_shell.env_checks import check_docker_environment

environments: Dict[str, Dict[str, str]] = {
    "daffy": {},
    "daffy-staging": {
        "DOCKER_REGISTRY": "registry-stage2.duckietown.org",
        "DTSERVER": "https://challenges-stage.duckietown.org",
        "PIP_INDEX_URL": "https://staging.duckietown.org/root/devel/",
    },
}


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args: List[str]):
        version = shell.shell_config.duckietown_version
        envs = environments.get(version, {})
        dtslogger.info(f"Version: {version}\nUsing special envs:\n{json.dumps(envs, indent=2)}")
        check_package_version("duckietown-docker-utils-daffy", "6.0.78")
        from duckietown_docker_utils import generic_docker_run, ENV_REGISTRY

        parser = argparse.ArgumentParser(prog="dts challenges")

        parser.add_argument(
            "--image",
            default="${%s}/duckietown/duckietown-challenges-cli:daffy-amd64" % ENV_REGISTRY,
            help="Which image to use",
        )

        parser.add_argument("--entrypoint", default=None)
        parser.add_argument("--shell", default=False, action="store_true")
        parser.add_argument("--root", default=False, action="store_true")
        parser.add_argument("--no-pull", action="store_true", default=False, help="")
        # parser.add_argument('cmd', nargs='*')
        # find the first non- "-" entry
        parse_here = []
        parse_later = []

        for i, arg in enumerate(args):
            if not arg.startswith("-"):
                parse_later = args[i:]
                break
            else:
                parse_here.append(arg)

        parsed, rest = parser.parse_known_args(args=parse_here)
        rest += parse_later

        if rest and (rest[0] == "config"):
            return command_config(shell, rest[1:])

        # dtslogger.info(str(dict(args=args, parsed=parsed, rest=rest)))
        dt1_token = shell.get_dt1_token()
        client = check_docker_environment()

        docker_credentials = shell.shell_config.docker_credentials

        if "DT_MOUNT" in os.environ:
            development = True
        else:
            development = False

        timestamp = "{:%Y_%m_%d_%H_%M_%S_%f}".format(datetime.now())
        container_name = f"challenges_{timestamp}_{random.randint(0, 10)}"
        user = getpass.getuser()
        logname = f"/tmp/{user}/duckietown/dt-shell-commands/challenges/{container_name}.txt"

        gdr = generic_docker_run(
            client,
            as_root=parsed.root,
            image=parsed.image,
            commands=rest,
            shell=parsed.shell,
            entrypoint=parsed.entrypoint,
            docker_secret=None,
            docker_username=None,
            dt1_token=dt1_token,
            development=development,
            container_name=container_name,
            pull=not parsed.no_pull,
            logname=logname,
            read_only=False,
            docker_credentials=docker_credentials,
        )
        if gdr.retcode:
            msg = f"Execution of docker image failed. Return code: {gdr.retcode}."
            msg += f"\n\nThe log is available at {logname}"
            raise UserError(msg)


def command_config(shell: DTShell, args: List[str]):
    parser = argparse.ArgumentParser(prog="dts challenges config")
    parser.add_argument("--docker-server", dest="server", help="Docker server", default="docker.io")
    parser.add_argument("--docker-username", dest="username", help="Docker username", required=True)
    parser.add_argument(
        "--docker-password", dest="password", help="Docker password or Docker token", required=True
    )
    parsed = parser.parse_args(args)

    username = parsed.username
    password = parsed.password

    server = parsed.server

    if server not in shell.shell_config.docker_credentials:
        shell.shell_config.docker_credentials[server] = {}
    if username is not None:
        shell.shell_config.docker_username = username
        shell.shell_config.docker_credentials[server]["username"] = username
    if password is not None:
        shell.shell_config.docker_password = password
        shell.shell_config.docker_credentials[server]["secret"] = password

    shell.save_config()
    # if username is None and password is None:
    #     msg = "You should pass at least one parameter."
    #     msg += "\n\n" + parser.format_help()
    #     raise UserError(msg)
