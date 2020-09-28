import argparse
from datetime import datetime
from typing import List

from challenges.challenges_cmd_utils import check_package_version
from dt_shell import DTCommandAbs, DTShell, UserError
from dt_shell.env_checks import (check_docker_environment, get_dockerhub_username_and_password)


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell: DTShell, args: List[str]):
        check_package_version('duckietown-docker-utils-daffy', '6.0.3')
        from duckietown_docker_utils.docker_run import generic_docker_run

        parser = argparse.ArgumentParser()

        parser.add_argument('--image',
                            default='${AIDO_REGISTRY}/duckietown/duckietown-challenges-cli:daffy',
                            help="Which image to use")

        parser.add_argument('--entrypoint', default=None)
        parser.add_argument('--shell', default=False, action='store_true')
        parser.add_argument('--root', default=False, action='store_true')
        parser.add_argument('--dev', default=False, action='store_true')
        parser.add_argument("--no-pull", action="store_true", default=False, help="")
        # parser.add_argument('cmd', nargs='*')
        parsed, rest = parser.parse_known_args(args=args)
        if not rest:
            # TODO: help
            print('need a command')
            return
        if rest[0] == 'config':
            return command_config(shell, rest[1:])

        # dtslogger.info(str(dict(args=args, parsed=parsed, rest=rest)))
        dt1_token = shell.get_dt1_token()
        username, secret = get_dockerhub_username_and_password()
        check_docker_environment()
        client = check_docker_environment()
        container_name = 'challenges-docker'

        timestamp = "{:%Y_%m_%d_%H_%M_%S}.txt".format(datetime.now())
        logname = f'/tmp/{container_name}-{timestamp}'

        gdr = \
            generic_docker_run(client,
                               as_root=parsed.root,
                               image=parsed.image,
                               commands=rest,
                               shell=parsed.shell,
                               entrypoint=parsed.entrypoint,
                               docker_secret=secret,
                               docker_username=username,
                               dt1_token=dt1_token,
                               development=parsed.dev,
                               container_name=container_name,
                               pull=not parsed.no_pull,
                               logname=logname)
        if gdr.retcode:
            msg = 'Execution of docker image failed.'
            msg += f'\n\nThe log is available at {logname}'
            raise UserError(msg)


def command_config(shell: DTShell, args: List[str]):
    parser = argparse.ArgumentParser(prog="dts challenges config")
    parser.add_argument("--docker-username", dest="username", help="Docker username")
    parser.add_argument("--docker-password", dest="password", help="Docker password")
    parsed = parser.parse_args(args)

    username = parsed.username
    password = parsed.password

    if username is not None:
        shell.shell_config.docker_username = username
    if password is not None:
        shell.shell_config.docker_password = password
    shell.save_config()
    if username is None and password is None:
        msg = 'You should pass at least one parameter.'
        msg += '\n\n' + parser.format_help()
        raise UserError(msg)
