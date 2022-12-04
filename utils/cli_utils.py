import os
import subprocess
import sys
from shutil import which

from dt_shell import dtslogger

__all__ = ["get_clean_env", "start_command_in_subprocess", "ask_confirmation", "check_program_dependency"]


def get_clean_env():
    env = {}
    env.update(os.environ)

    V = "DOCKER_HOST"
    if V in env:
        msg = "I will ignore %s in the environment because we want to run things on the laptop." % V
        dtslogger.info(msg)
        env.pop(V)

    return env


def start_command_in_subprocess(run_cmd, env=None, shell=True, nostdout=False, nostderr=False, retry=1):
    retry = max(retry, 1)
    if env is None:
        env = get_clean_env()
    if shell and not isinstance(run_cmd, str):
        run_cmd = " ".join(run_cmd)
    for trial in range(retry):
        if trial > 0:
            msg = f"An error occurred while running {str(run_cmd)}, retrying (trial={trial + 1})"
            dtslogger.warning(msg)
        dtslogger.debug(" $ %s" % str(run_cmd))
        ret = subprocess.run(
            run_cmd,
            shell=shell,
            stdin=sys.stdin,
            stderr=subprocess.PIPE if nostderr else sys.stderr,
            stdout=subprocess.PIPE if nostdout else sys.stdout,
            env=env,
        )
        # exit codes: 0 (ok), 130 (ctrl-c)
        if ret.returncode in [0, 130]:
            break
        else:
            if retry == 1 or retry == trial + 1:
                msg = (
                    f'Error occurred while running "{str(run_cmd)}", '
                    f"please check and retry ({ret.returncode})"
                )
                raise Exception(msg)


def ask_confirmation(message, default="n", question="Do you confirm?", choices=None):
    binary_question = False
    if choices is None:
        choices = {"y": "Yes", "n": "No"}
        binary_question = True
    choices_str = " ({})".format(", ".join([f"{k}={v}" for k, v in choices.items()]))
    default_str = f" [{default}]" if default else ""
    while True:
        dtslogger.warn(f"{message.rstrip('.')}.")
        r = input(f"{question}{choices_str}{default_str}: ")
        if r.strip() == "":
            r = default
        r = r.strip().lower()
        if binary_question:
            if r in ["y", "yes", "yup", "yep", "si", "aye"]:
                return True
            elif r in ["n", "no", "nope", "nay"]:
                return False
        else:
            if r in choices:
                return r


def check_program_dependency(exe):
    p = which(exe)
    if p is None:
        dtslogger.error(
            f"The command '{exe}' is required but could not be found. "
            f"Please, install it before continuing."
        )
        exit(1)
    dtslogger.debug("Found %r at %s" % (exe, p))
