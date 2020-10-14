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
        parser.add_argument("--preview",default=0,action=1,help="")

    @staticmethod
    def command(shell:DTShell,args, **kwargs):
        parsed = DTCommand._parse_args(args)
        if "parsed" in kwargs:
            parsed.__dict__.update(kwargs["parsed"].__dict__)
        
        local_directories = glob("duckuments-dist/*/")
        if len(local_directories)<1:
            dtslogger.error("Cannot find a compiled book. Exiting....")
            exit(2)
        else:
            for entry in local_directories:
                if "junit" not in entry:
                    directory_name = entry.replace("duckuments-dist/","")
                    directory_name = directory_name.replace("/","")
            dtslogger.info("Currently the book is: %s" % directory_name)
        main = "file://"+os.getcwd()+"/duckuments-dist/"+directory_name+"/out/index.html"
        webbrowser.open(main,new=2)