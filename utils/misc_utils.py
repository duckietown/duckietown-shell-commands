import ipaddress
import subprocess
from shutil import which

__all__ = ["human_time", "human_size", "sanitize_hostname", "sudo_open", "parse_version",
           "noop_command", "failed_to_load_command"]

from types import SimpleNamespace

from dt_shell import DTCommandAbs, dtslogger


class NoOpCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        pass


class FailedToLoadCommand(NoOpCommand):

    @staticmethod
    def command(shell, args):
        dtslogger.warning("This command was not loaded")


noop_command = SimpleNamespace(DTCommand=NoOpCommand)
failed_to_load_command = SimpleNamespace(DTCommand=FailedToLoadCommand)


def human_time(time_secs, compact=False):
    label = lambda s: s[0] if compact else " " + s
    days = int(time_secs // 86400)
    hours = int(time_secs // 3600 % 24)
    minutes = int(time_secs // 60 % 60)
    seconds = int(time_secs % 60)
    parts = []
    if days > 0:
        parts.append("{}{}".format(days, label("days")))
    if days > 0 or hours > 0:
        parts.append("{}{}".format(hours, label("hours")))
    if days > 0 or hours > 0 or minutes > 0:
        parts.append("{}{}".format(minutes, label("minutes")))
    parts.append("{}{}".format(seconds, label("seconds")))
    return ", ".join(parts)


def human_size(value, suffix="B", precision=2):
    for unit in ["", "K", "M", "G", "T", "P", "E", "Z"]:
        if abs(value) < 1024.0:
            # noinspection PyStringFormat
            return f"%3.{precision}f %s%s" % (value, unit, suffix)
        value /= 1024.0
    # noinspection PyStringFormat
    return f"%.{precision}f%s%s".format(value, "Yi", suffix)


def sanitize_hostname(hostname):
    try:
        ipaddress.ip_address(hostname)
        return hostname
    except ValueError:
        return f"{hostname}.local" if not hostname.endswith(".local") else hostname


def sudo_open(path, mode, *_, **__):
    if mode not in ["r", "w", "rb", "wb"]:
        raise ValueError(f"Mode '{mode}' not supported.")
    mode = mode[0]
    tool = "cat" if mode == "r" else "tee"
    # check if dependencies are met
    if which(tool) is None:
        raise ValueError(f"The command `{tool}` could not be found. Please, install it first.")
    # ---
    proc = subprocess.Popen(["sudo", tool, path], stdout=subprocess.PIPE, stdin=subprocess.PIPE)
    return proc.stdout if mode == "r" else proc.stdin


def parse_version(v: str) -> tuple:
    return tuple(map(int, (v.split("."))))
