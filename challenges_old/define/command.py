import argparse
import os

from challenges.challenges_cmd_utils import check_duckietown_challenges_version, wrap_server_operations
from dt_shell import DTCommandAbs, DTShell, dtslogger, UserError

from dt_shell.env_checks import check_docker_environment, get_dockerhub_username


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):

        check_duckietown_challenges_version()

        token = shell.get_dt1_token()

        parser = argparse.ArgumentParser()
        parser.add_argument("--config", default="challenge.yaml", help="YAML configuration file")

        parser.add_argument("--no-cache", default=False, action="store_true")
        parser.add_argument("--steps", default=None, help="Which steps (comma separated)")
        parser.add_argument("--force-invalidate-subs", default=False, action="store_true")
        parser.add_argument("-C", dest="cwd", default=None, help="Base directory")
        parser.add_argument("--impersonate", type=str, default=None)
        parser.add_argument("--pull", default=False, action="store_true")

        parsed = parser.parse_args(args)
        impersonate = parsed.impersonate

        client = check_docker_environment()
        if client is None:  # To remove when done
            client = check_docker_environment()

        if parsed.cwd is not None:
            dtslogger.info("Changing to directory %s" % parsed.cwd)
            os.chdir(parsed.cwd)

        no_cache = parsed.no_cache

        fn = os.path.join(parsed.config)
        if not os.path.exists(fn):
            msg = "File %s does not exist." % fn
            raise UserError(msg)

        from duckietown_challenges import read_yaml_file, ChallengeDescription, logger as dc_logger
        from duckietown_challenges.others import dts_define

        data = read_yaml_file(fn)

        if "description" not in data or data["description"] is None:
            fnd = os.path.join(os.path.dirname(fn), "challenge.description.md")
            if os.path.exists(fnd):
                desc = open(fnd).read()
                data["description"] = desc
                msg = "Read description from %s" % fnd
                dtslogger.info(msg)

        base = os.path.dirname(fn)
        dtslogger.info(f"data {data}")
        challenge = ChallengeDescription.from_yaml(data)
        assert challenge.date_close.tzinfo is not None, (
            challenge.date_close.tzinfo,
            challenge.date_open.tzinfo,
        )
        assert challenge.date_open.tzinfo is not None, (
            challenge.date_close.tzinfo,
            challenge.date_open.tzinfo,
        )

        username = get_dockerhub_username()
        dc_logger.info("read challenge", challenge=challenge)
        with wrap_server_operations():
            dts_define(token=token, impersonate=impersonate,
                       parsed=parsed, challenge=challenge, base=base, client=client, no_cache=no_cache,
                       username=username)
