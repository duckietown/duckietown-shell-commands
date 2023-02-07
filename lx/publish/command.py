import argparse
import json
import os
import pathlib
from typing import Optional

from dt_shell import DTCommandAbs, dtslogger, DTShell

from utils.dtproject_utils import DTProject
from utils.git_utils import get_branches
from utils.json_schema_form_utils import open_form


class DTCommand(DTCommandAbs):
    help = "Publishes a Duckietown Learning Experience to the LX repository"

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        # Configure args
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-C",
            "--workdir",
            default=os.getcwd(),
            help="Directory containing the LX project to publish"
        )

        # Get pre-parsed or parse arguments
        parsed = kwargs.get("parsed", None)
        if not parsed:
            parsed, _ = parser.parse_known_args(args=args)

        # Ensure this is an LX template
        parsed.workdir = os.path.abspath(parsed.workdir)
        project: DTProject = DTProject(parsed.workdir)
        if project.type != "development-lx":
            dtslogger.error(f"Project of type '{project.type}' not supported. You need to be in a "
                            f"'template-exercise' project directory to publish with 'dts lx publish'.")
            return False

        #TODO: Get updated form defaults

        form_values: Optional[dict] = open_form_from_schema(
            shell,
            "lx-publish",
            "v3",
            title="Publish your Learning Experience",
            subtitle="Populate the fields below to publish your Learning Experience",
            completion_message="Uploading LX ...\n You can now close this page and return to the terminal."
        )

        dtslogger.debug(str(form_values))

        # TODO: Confirm that all lx directories exist and are the correct project type

        # TODO: Create a .temp dir and clone the lx destination repositories into it

        # TODO: Update the repo dirs and push

        # TODO: Clean up and msg success

    @staticmethod
    def complete(shell, word, line):
        return []
