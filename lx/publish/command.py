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
        if project.type != "template-exercise":
            dtslogger.error(f"Project of type '{project.type}' not supported. You need to be in a "
                            f"'template-exercise' project directory to publish with 'dts lx publish'.")
            return False

        # Get the form data
        assets_dir: str = os.path.join(pathlib.Path(__file__).parent.absolute(), "assets", "lx-publisher")
        schema_fpath: str = os.path.join(assets_dir, "schema.json")
        with open(schema_fpath, "rt") as fin:
            schema: dict = json.load(fin)

        # Load the duckietown-lx repo branches into the form
        schema["schema"]["branch"]["enum"] = get_branches("duckietown", "duckietown-lx")

        values: Optional[dict] = open_form(
            shell,
            schema=schema,
            title="Publish your Learning Experience",
            subtitle="Populate the fields below to publish your Learning Experience to the Duckietown LX repository",
            icon_fpath=os.path.join(assets_dir, "icon.png"),
        )

        # TODO: Pushing an ind. dir to the repo is non-trivial with the api. Do we need this?
        dtslogger.info(str(values))

    @staticmethod
    def complete(shell, word, line):
        return []
