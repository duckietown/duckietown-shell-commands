import os
import sys
import subprocess
from shutil import which

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
            break
        else:
            if retry == 1 or retry == trial+1:
                msg = f"Error occurred while running {run_cmd}, please check and retry ({return_code})"
                raise Exception(msg)


class ProgressBar:

    def __init__(self):
        self._finished = False

    def update(self, percentage):
        if self._finished:
            return
        # compile progress bar
        pbar = "Progress: ["
        # progress
        pbar += "=" * percentage
        if percentage < 100:
            pbar += ">"
        pbar += " " * (100 - percentage - 1)
        # this ends the progress bar
        pbar += f"] {percentage}%"
        # print
        sys.stdout.write(pbar)
        sys.stdout.flush()
        # return to start of line
        sys.stdout.write("\b" * len(pbar))
        # end progress bar
        if percentage >= 100:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._finished = True


def ask_confirmation(message, default='y'):
    default_str = f" [{default}]" if default else ""
    while True:
        dtslogger.warn(f"{message.rstrip('.')}.")
        r = input(f'Do you confirm?{default_str}: ')
        if r.strip() == '':
            r = default
        if r.strip().lower() in ['y', 'yes', 'yup', 'yep', 'si', 'aye']:
            return True
        elif r.strip().lower() in ['n', 'no', 'nope', 'nay']:
            return False


def check_program_dependency(exe):
    p = which(exe)
    if p is None:
        raise Exception("Could not find program %r" % exe)
    dtslogger.debug("Found %r at %s" % (exe, p))