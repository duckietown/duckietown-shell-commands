import argparse
import os
import webbrowser
from glob import glob

from dt_shell import DTCommandAbs, DTShell, dtslogger

class DTCommand(DTCommandAbs):
    help = "Opens compiled docs"

    @staticmethod
    def _parse_args(args):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument("--all", action='store_true',
                            help="Show build artifact log during preview.")
        parsed, _ = parser.parse_known_args(args=args)
        return parsed

    @staticmethod
    def command(shell: DTShell, args):
        parsed = DTCommand._parse_args(args)
        local_directories = glob("duckuments-dist/*/")
        if len(local_directories) < 1:
            dtslogger.warning("Cannot find a compiled book. Trying to trigger a document build first!")
            shell.include.docs.build.command(shell, [])
            local_directories = glob("duckuments-dist/*/")
            if len(local_directories) < 1:
                dtslogger.error("Tried building the duckuments but failed!")
                exit(2)
        for entry in local_directories:
            if "junit" not in entry:
                directory_name = entry.replace("duckuments-dist/", "")
                directory_name = directory_name.replace("/", "")
        dtslogger.info("Currently the book is: %s" % directory_name)
        main = "file://" + os.getcwd() + "/duckuments-dist/" + directory_name + "/out/index.html"
        webbrowser.open(main, new=1)
        if parsed.all:
            error_file = "file://" + os.getcwd() + "/duckuments-dist/errors.html"
            warning_file = "file://" + os.getcwd() + "/duckuments-dist/warnings.html"
            todo_file = "file://" + os.getcwd() + "/duckuments-dist/tasks.html"
            webbrowser.open_new_tab(error_file)
            webbrowser.open_new_tab(warning_file)
            webbrowser.open_new_tab(todo_file)

    @staticmethod
    def complete(shell, word, line):
        return []