import os
import subprocess
import sys

from dt_shell import dtslogger


def get_clean_env():
    env = {}
    env.update(os.environ)

    V = "DOCKER_HOST"
    if V in env:
        msg = (
            "I will ignore %s in the environment because we want to run things on the laptop."
            % V
        )
        dtslogger.info(msg)
        env.pop(V)
    return env


def start_command_in_subprocess(run_cmd, env=None):
    if env is None:
        env = get_clean_env()

    print("Running %s" % run_cmd)
    ret = subprocess.call(
        run_cmd,
        shell=True,
        stdin=sys.stdin,
        stderr=sys.stderr,
        stdout=sys.stdout,
        env=env,
    )
    if ret == 0:
        print("Done!")
    else:
        msg = "Error occurred while running %s, please check and retry (%s)." % (
            run_cmd,
            ret,
        )
        raise Exception(msg)
