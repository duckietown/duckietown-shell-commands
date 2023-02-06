import argparse
import json
import os
import pathlib
from typing import Optional

from dt_shell import DTCommandAbs, dtslogger, DTShell

from utils.json_schema_form_utils import open_form


class DTCommand(DTCommandAbs):
    help = "Creates a new Learning Experience"

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        # Configure args
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-C",
            "--workdir",
            default=os.getcwd(),
            help="Directory to generate the LX project into"
        )

        # Get pre-parsed or parse arguments
        parsed = kwargs.get("parsed", None)
        if not parsed:
            parsed, _ = parser.parse_known_args(args=args)

        # Get the working dir to generate the LX into
        parsed.workdir = os.path.abspath(parsed.workdir)

        # Get the form data
        assets_dir: str = os.path.join(pathlib.Path(__file__).parent.absolute(), "assets", "new-lx")
        schema_fpath: str = os.path.join(assets_dir, "schema.json")
        with open(schema_fpath, "rt") as fin:
            schema: dict = json.load(fin)

        values: Optional[dict] = open_form(
            shell,
            schema=schema,
            title="Create new Learning Experience",
            subtitle="Populate the fields below to create a new Learning Experience",
            icon_fpath=os.path.join(assets_dir, "icon.png"),
        )

        # TODO: do something else with these
        dtslogger.info(str(values))

    @staticmethod
    def complete(shell, word, line):
        return []
