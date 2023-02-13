import argparse
import os
import tempfile
from typing import Optional

from dt_shell import DTCommandAbs, dtslogger, DTShell

from utils.dtproject_utils import DTProject
from utils.git_utils import clone_repository
from utils.json_schema_form_utils import open_form_from_schema


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

        parser.add_argument(
            "-n",
            "--dry-run",
            default=os.getcwd(),
            help="Verify that your project is ready to push without actually sending the files"
        )

        # Get pre-parsed or parse arguments
        parsed = kwargs.get("parsed", None)
        if not parsed:
            parsed, _ = parser.parse_known_args(args=args)

        # Ensure this is an LX template
        parsed.workdir = os.path.abspath(parsed.workdir)
        project: DTProject = DTProject(parsed.workdir)
        if project.type != "lx-development":
            dtslogger.error(f"Project of type '{project.type}' not supported. You need to be in a "
                            f"'lx-development' project directory to publish with 'dts lx publish'."
                            f"This type of project can be generated with 'dts lx create'.")
            return False

        #TODO: Get updated form defaults

        svalues: Optional[dict] = open_form_from_schema(
            shell,
            "lx-publish",
            "v3",
            title="Publish your Learning Experience",
            subtitle="Populate the fields below to publish your Learning Experience",
            completion_message="Uploading LX ...\n You can now close this page and return to the terminal."
        )

        dtslogger.debug(f"Form values received: '{str(svalues)}'")

        # TODO: Confirm that all lx directories exist and are the correct project type

        # TODO: Update the recipe references

        # Create a .temp dir and clone the current versions of the lx destination repositories
        with tempfile.TemporaryDirectory() as temp_dir:
            lx_dest: str = clone_repository(svalues["lx_repo"], svalues["lx_branch"], temp_dir)
            recipe_dest: str = clone_repository(svalues["recipe_repo"], svalues["recipe_branch"], temp_dir)
            sol_dest: str = clone_repository(svalues["solution_repo"], svalues["solution_branch"], temp_dir)

        # TODO: Update the repo dirs and push

        # TODO: Clean up and msg success

    @staticmethod
    def complete(shell, word, line):
        return []
