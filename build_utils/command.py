import argparse
import getpass
import os
import random
from datetime import datetime
from typing import List

from dt_shell import DTCommandAbs, DTShell, UserError
from dt_shell.env_checks import check_docker_environment


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args: List[str]):
        from duckietown_docker_utils import generic_docker_run, ENV_REGISTRY

        parser = argparse.ArgumentParser()

        parser.add_argument(
            "--image",
            default="${%s}/duckietown/duckietown-challenges-cli:ente" % ENV_REGISTRY,
            help="Which image to use",
        )

        # parser.add_argument('--entrypoint', default=None)
        parser.add_argument("--shell", default=False, action="store_true")
        parser.add_argument("--root", default=False, action="store_true")
        # parser.add_argument('--dev', default=False, action='store_true')
        parser.add_argument("--no-pull", action="store_true", default=False, help="")
        # parser.add_argument('cmd', nargs='*')
        parsed, rest = parser.parse_known_args(args=args)

        if "DT_MOUNT" in os.environ:
            development = True
        else:
            development = False
        # dtslogger.info(str(dict(args=args, parsed=parsed, rest=rest)))
        token: str = shell.profile.secrets.dt_token
        # username, secret = get_dockerhub_username_and_password()
        client = check_docker_environment()
        shell_config = shell.shell_config

        timestamp = "{:%Y_%m_%d_%H_%M_%S_%f}".format(datetime.now())
        container_name = f"build_utils_{timestamp}_{random.randint(0, 10)}"
        user = getpass.getuser()
        logname = f"/tmp/{user}/duckietown/dt-shell-commands/build_utils/{container_name}.txt"

        no_pull = parsed.no_pull
        gdr = generic_docker_run(
            client,
            entrypoint="dt-build_utils-cli",
            as_root=parsed.root,
            image=parsed.image,
            commands=rest,
            shell=parsed.shell,
            docker_secret=None,
            docker_username=None,
            dt1_token=token,
            development=development,
            container_name=container_name,
            pull=not no_pull,
            read_only=False,
            detach=True,
            logname=logname,
            docker_credentials=shell_config.docker_credentials,
        )
        if gdr.retcode:
            msg = f"Execution of docker image failed. Return code: {gdr.retcode}."
            msg += f"\n\nThe log is available at {logname}"
            raise UserError(msg)
