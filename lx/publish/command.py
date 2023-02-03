import json
import os
import pathlib
from typing import Optional

from dt_shell import DTCommandAbs, dtslogger, DTShell

from utils.git_utils import get_branches
from utils.json_schema_form_utils import open_form


class DTCommand(DTCommandAbs):
    help = "Publishes a Duckietown Learning Experience to the LX repository"

    # TODO: Initial internal version should update form with dropdown of current duckietown-lx branches
    print(get_branches("duckietown", "duckietown-lx"))

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        assets_dir: str = os.path.join(pathlib.Path(__file__).parent.absolute(), "assets", "lx-publisher")
        schema_fpath: str = os.path.join(assets_dir, "schema.json")
        with open(schema_fpath, "rt") as fin:
            schema: dict = json.load(fin)
        #
        values: Optional[dict] = open_form(
            shell,
            schema=schema,
            title="Publish your Learning Experience",
            subtitle="Populate the fields below to publish your Learning Experience to the Duckietown LX repository",
            icon=os.path.join(assets_dir, "icon.png"),
        )

        # TODO: do something else with these
        dtslogger.info(str(values))

    @staticmethod
    def complete(shell, word, line):
        return []
