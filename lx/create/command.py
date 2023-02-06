import argparse
import os
import re
from typing import Optional

from dt_shell import DTCommandAbs, dtslogger, DTShell

from utils.assets_utils import load_dtproject, load_template
from utils.git_utils import clone_repository
from utils.json_schema_form_utils import open_form_from_schema
from utils.template_utils import rename_template


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
        form_values: Optional[dict] = open_form_from_schema(
            shell,
            "lx-create",
            "v3",
            title="Create new Learning Experience",
            subtitle="Populate the fields below to create a new Learning Experience",
            completion_message="Generating your LX ...\n You can now close this page and return to the terminal."
        )
        dtslogger.debug(f"Form values received: '{str(form_values)}'")

        # Load in the template configuration and multi-use form data
        template_config: dict = load_template("lx", "v3")
        template_version: str = template_config["template-version"]
        lx_repo: str = template_config["lx-template-repo"]
        recipe_repo: str = template_config["lx-recipe-template-repo"]
        project_name: str = form_values["name"]
        safe_project_name: str = re.sub(r'[^\w\s\d@]', "", project_name.replace(" ", "_"))

        # Create the project and update the workdir

        # Clone lx-template and lx-recipe-template into the workdir
        dtslogger.info("Generating custom LX and recipe ...")
        lx_path: str = clone_repository(lx_repo, template_version, parsed.workdir)
        recipe_path: str = clone_repository(recipe_repo, template_version, parsed.workdir)

        # Rename the templates
        rename_template(lx_path, safe_project_name)
        rename_template(recipe_path, safe_project_name)

        dtslogger.info("Created LX and recipe directories.")
        dtslogger.info("Customizing the LX ...")

    @staticmethod
    def complete(shell, word, line):
        return []
