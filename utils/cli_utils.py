import os
import sys
import math
import subprocess
from shutil import which

from dt_shell import dtslogger


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
            msg = f"An error occurred while running {str(run_cmd)}, retrying (trial={trial+1})"
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


class ProgressBar:
    def __init__(self, scale=1.0, buf=sys.stdout, header="Progress"):
        self._finished = False
        self._buffer = buf
        self._header = header
        self._last_value = -1
        self._scale = max(0.0, min(1.0, scale))
        self._max = int(math.ceil(100 * self._scale))

    def set_header(self, header):
        self._header = header

    def update(self, percentage):
        percentage_int = int(max(0, min(100, percentage)))
        if percentage_int == self._last_value:
            return
        percentage = int(math.ceil(percentage * self._scale))
        if self._finished:
            return
        # compile progress bar
        pbar = f"{self._header}: [" if self._scale > 0.5 else "["
        # progress
        pbar += "=" * percentage
        if percentage < self._max:
            pbar += ">"
        pbar += " " * (self._max - percentage - 1)
        # this ends the progress bar
        pbar += "] {:d}%".format(percentage_int)
        # print
        self._buffer.write(pbar)
        self._buffer.flush()
        # return to start of line
        self._buffer.write("\b" * len(pbar) + '\x1b[2K')
        # end progress bar
        if percentage >= self._max:
            self._buffer.write("Done!\n")
            self._buffer.flush()
            self._finished = True
        self._last_value = percentage_int

    def done(self):
        self.update(100)


def ask_confirmation(message, default="y", question="Do you confirm?", choices=None):
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
        raise Exception("Could not find program %r" % exe)
    dtslogger.debug("Found %r at %s" % (exe, p))
