import ipaddress
import json
import os
import subprocess
import traceback
import webbrowser
import random
import string
from shutil import which

__all__ = ["human_time", "human_size", "sanitize_hostname", "sudo_open", "parse_version", "indent_block",
           "get_user_login", "pretty_json", "versiontuple", "render_version", "pretty_exc", "NotSet",
           "hide_string", "SimpleWindowBrowser"]

from typing import Any

from dt_shell import dtslogger

NotSet = object()


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
    if "://" in hostname:
        return hostname
    try:
        ip = hostname.split(":")[0]
        ipaddress.ip_address(ip)
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


def get_first_numeric_part(s: str) -> int:
    c = ''
    for i in s:
        if i.isdigit():
            c += i
        else:
            break
    if not c:
        return 0
    return int(c)
        
def parse_version(v: str) -> tuple:
    return tuple(get_first_numeric_part(_) for _ in v.split("."))


def render_version(t: tuple) -> str:
    return ".".join(str(_) for _ in t)


def indent_block(s: str, indent: int = 4) -> str:
    space: str = " " * indent
    return space + f"\n{space}".join(s.splitlines())


def pretty_json(data: Any, indent: int = 0) -> str:
    return indent_block(json.dumps(data, sort_keys=True, indent=4), indent=indent)


def pretty_exc(exc: Exception, indent: int = 0) -> str:
    return indent_block(''.join(traceback.TracebackException.from_exception(exc).format()), indent=indent)


def get_user_login() -> str:
    try:
        user = os.getlogin()
    # fall back on getpass for terminals not registering with utmp
    except (OSError, FileNotFoundError):
        import getpass
        user = getpass.getuser()
    return user


def versiontuple(version: str):
    return tuple(map(int, (version.split("."))))


def hide_string(s: str, k: int = 3) -> str:
    hidden = "*" * (len(s) - k) + s[-k:]
    return hidden


class SimpleWindowBrowser:
    def __init__(self):
        try:
            self._browser = webbrowser.get()
        except webbrowser.Error:
            dtslogger.warning("We could not found a web browser to open the code editor in. Please, use the "
                              "URL given above in the web browser you prefer instead.")
            self._browser = None
            # with Chrome, we can use --app to open a simple window
        if isinstance(self._browser, webbrowser.Chrome):
            self._browser.remote_args = ["--app=%s"]

    def open(self, url: str) -> bool:
        if self._browser is None:
            return False
        try:
            return self._browser.open(url)
        except:
            webbrowser.open(url)


def random_string(length=6):
    return ''.join(random.choices(string.ascii_lowercase, k=length))
