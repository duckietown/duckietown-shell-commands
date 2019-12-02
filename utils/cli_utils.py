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


def start_command_in_subprocess(run_cmd, env=None, shell=True, nostdout=False, nostderr=False, retry=1):
    retry = max(retry, 1)
    if env is None:
        env = get_clean_env()

    for trial in range(retry):
        if trial > 0:
            msg = f"An error occurred while running r{run_cmd}, retrying (trial={trial+1})"
            dtslogger.warning(msg)
        dtslogger.debug(run_cmd)
        return_code = subprocess.call(
            run_cmd,
            shell=shell,
            stdin=sys.stdin,
            stderr=None if nostderr else sys.stderr,
            stdout=None if nostdout else sys.stdout,
            env=env,
        )
        if return_code == 0:
            print("Done!")
        else:
            if retry == 1 or retry == trial+1:
                msg = f"Error occurred while running {run_cmd}, please check and retry ({return_code})"
                raise Exception(msg)
