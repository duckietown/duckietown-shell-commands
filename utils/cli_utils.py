import os
import subprocess
import sys
from shutil import which
from typing import Optional

from dt_shell import dtslogger, UserError

__all__ = ["get_clean_env", "start_command_in_subprocess", "ask_confirmation", "ensure_command_is_installed"]


COMMAND_INSTALL_PACKAGES = {
    "mkfs.fat": "dosfstools",
    "fatlabel": "dosfstools",
}


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


def ensure_command_is_installed(command, dependant: Optional[str] = None):
    command_path: Optional[str] = which(command)
    if command_path is None:
        extra: str = ""
        if dependant:
            extra = f" by '{dependant}'"
        package: Optional[str] = COMMAND_INSTALL_PACKAGES.get(command)
        install_hint: str
        if package is None:
            install_hint = "Please, install it before continuing."
        else:
            install_hint = (
                f"Install the package '{package}' and retry "
                f"(for Debian/Ubuntu: sudo apt install -y {package})."
            )
        msg = f"""

        The command '{command}' is required{extra}. {install_hint}

        """
        raise UserError(msg)
    else:
        dtslogger.debug(f"Command '{command}' found: {command_path}")
