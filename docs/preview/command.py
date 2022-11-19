import argparse
import getpass
import os
import subprocess
import sys
import webbrowser
from glob import glob

from dt_shell import DTCommandAbs, DTShell, dtslogger
from dt_shell.env_checks import check_docker_environment

from utils.docker_utils import replace_important_env_vars


class DTCommand(DTCommandAbs):
    help = "Opens compiled docs"

    @staticmethod
    def _parse_args(args):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument("--preview", default="1",
                            help="Set Preview Level: 0:Disabled 1:MainOnly 2:Showall")
        parsed, _ = parser.parse_known_args(args=args)
        return parsed

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = DTCommand._parse_args(args)
        if "parsed" in kwargs:
            parsed.__dict__.update(kwargs["parsed"].__dict__)

        local_directories = glob("duckuments-dist/*/")
        if len(local_directories) < 1:
            dtslogger.error("Cannot find a compiled book. Exiting....")
            exit(2)
        else:
            for entry in local_directories:
                if "junit" not in entry:
                    directory_name = entry.replace("duckuments-dist/", "")
                    directory_name = directory_name.replace("/", "")
            dtslogger.info("Currently the book is: %s" % directory_name)
        main = "file://" + os.getcwd() + "/duckuments-dist/" + directory_name + "/out/index.html"
        if parsed.preview == "1":
            webbrowser.open(main, new=2)
        if parsed.preview == "2":
            error_file = "file://" + os.getcwd() + "/duckuments-dist/errors.html"
            warning_file = "file://" + os.getcwd() + "/duckuments-dist/warnings.html"
            todo_file = "file://" + os.getcwd() + "/duckuments-dist/tasks.html"
            webbrowser.open(error_file, new=2)
            webbrowser.open(warning_file, new=2)
            webbrowser.open(todo_file, new=2)
            webbrowser.open(main, new=2)

    @staticmethod
    def complete(shell, word, line):
        return []