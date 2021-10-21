import argparse
import getpass
import os
import subprocess
import sys

from dt_shell import DTCommandAbs, DTShell, dtslogger
from dt_shell.env_checks import check_docker_environment
from duckietown_docker_utils import ENV_REGISTRY, replace_important_env_vars


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):

        parser = argparse.ArgumentParser()

        parser.add_argument(
            "--image", default="${%s}/duckietown/docs-build:daffy" % ENV_REGISTRY, help="Which image to use"
        )

        parsed = parser.parse_args(args=args)

        check_docker_environment()

        image = replace_important_env_vars(parsed.image)

        pwd = os.getcwd()

        pwd1 = os.path.realpath(pwd)
        user = getpass.getuser()

        uid1 = os.getuid()

        if sys.platform == "darwin":
            flag = ":delegated"
        else:
            flag = ""

        cache = f"/tmp/{user}/cache"
        if not os.path.exists(cache):
            os.makedirs(cache)

        cmd = [
            "docker",
            "run",
            "-e",
            "USER=%s" % user,
            "-e",
            "USERID=%s" % uid1,
            # '-m', '4GB',
            "--user",
            "%s" % uid1,
            "-e",
            "COMPMAKE_COMMAND=rparmake",
            "-it",
            "-v",
            f"{pwd1}:/pwd{flag}",
            "--workdir",
            "/pwd",
            image,
        ]

        dtslogger.info("executing:\nls " + " ".join(cmd))

        try:
            p = subprocess.Popen(
                cmd,
                bufsize=0,
                executable=None,
                stdin=None,
                stdout=None,
                stderr=None,
                preexec_fn=None,
                shell=False,
                cwd=pwd,
                env=None,
            )
        except OSError as e:
            if e.errno == 2:
                msg = 'Could not find "docker" executable.'
                DTCommandAbs.fail(msg)
            raise

        p.communicate()
        dtslogger.info("\n\nCompleted.")


def system_cmd_result(pwd, cmd):
    s = subprocess.check_output(cmd, cwd=pwd)
    return s.decode("utf-8")
