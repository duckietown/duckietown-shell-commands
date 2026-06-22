import ipaddress
import json
import os
import shlex
import subprocess
import sys
import traceback
import webbrowser
import random
import string
from shutil import which

__all__ = ["human_time", "human_size", "sanitize_hostname", "sudo_open", "parse_version", "indent_block",
           "get_user_login", "pretty_json", "versiontuple", "render_version", "pretty_exc", "NotSet",
           "hide_string", "SimpleWindowBrowser", "pretty_yaml", "open_browser_url"]

from typing import Any

import yaml

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


def pretty_yaml(data: Any, indent: int = 0) -> str:
    return indent_block(yaml.safe_dump(data, sort_keys=True, indent=4), indent=indent)


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
    version_base = version.split("-")[0]
    return tuple(map(int, (version_base.split("."))))


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
            return open_browser_url(url)
        try:
            return self._browser.open(url)
        except Exception:
            return open_browser_url(url)


def open_browser_url(url: str) -> bool:
    browser = os.environ.get("BROWSER", "")
    browser_command = browser.strip()
    if browser_command:
        try:
            browser_args = shlex.split(browser_command)
            if browser_args:
                if any("%s" in arg for arg in browser_args):
                    command = [arg.replace("%s", url) for arg in browser_args]
                else:
                    command = [*browser_args, url]
                subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return True
        except Exception as error:
            dtslogger.debug(
                f"Could not launch browser via BROWSER={browser_command!r}: {error}"
            )
    try:
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import sys, webbrowser; webbrowser.open(sys.argv[1])",
                url,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except Exception as error:
        dtslogger.debug(f"Could not launch browser fallback process: {error}")
        return False


def random_string(length=6):
    return ''.join(random.choices(string.ascii_lowercase, k=length))
