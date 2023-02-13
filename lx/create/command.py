import argparse
import os
import re
from typing import Optional

from dt_shell import DTCommandAbs, dtslogger, DTShell

from utils.assets_utils import load_dtproject, load_template
from utils.git_utils import clone_unlinked_repo
from utils.json_schema_form_utils import open_form_from_schema
from utils.template_utils import DTTemplate, fill_template_file, fill_template_json


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
        parsed.workdir = os.path.abspath(parsed.workdir)

        # Get the form data
        svalues: Optional[dict] = open_form_from_schema(
            shell,
            "lx-create",
            "v3",
            title="Create New Learning Experience",
            subtitle="Populate the fields below to create a new Learning Experience",
            completion_message="Generating your LX ...\n You can now close this page and return to the terminal."
        )
        safe_name: str = re.sub(r'[^\w\s@]', "", svalues["name"]).replace(" ", "-").lower()
        # Clean some form values
        svalues["safe_name"] = safe_name  # file safe alternate name - ex. Robot Time! -> robot-time
        dtslogger.debug(f"Form values received: '{str(svalues)}'")

        # Load in the template configuration and update with user form values
        # The template placeholder values should match the form schema names
        config_raw: dict = load_template("lx", "v3")
        config = fill_template_json(config_raw, svalues)
        print("AFTER", config)
        version: str = config["template-version"]

        # Create the project and update the workdir
        create_dir: str = os.path.join(parsed.workdir, safe_name)
        if not os.path.exists(create_dir):
            os.makedirs(create_dir)

        # Fill and save the .dtproject file
        temp = load_dtproject("lx", "v3")
        temp_filled = [DTTemplate(line).safe_substitute(config["lx-dev-dtproject"]) for line in temp]
        with open(os.path.join(create_dir, ".dtproject"), "w") as dtproject_file:
            dtproject_file.writelines(temp_filled)

        # Clone lx-template and lx-recipe-template into the workdir renamed and stripped of .git
        dtslogger.info("Generating custom LX and recipe ...")
        lx_path: str = clone_unlinked_repo(config["lx-template-repo"], version, create_dir, safe_name+"-lx")
        recipe_path: str = clone_unlinked_repo(config["recipe-template-repo"], version, create_dir, safe_name+"-recipe")
        solution_path: str = clone_unlinked_repo(config["lx-template-repo"], version, create_dir, safe_name+"-solution")

        dtslogger.info("Created LX and recipe directories.")
        dtslogger.info("Customizing the LX ...")

        # Update the template files with merged configuration and user values
        # Not included in first config: challenge definitions
        file_updates: dict = {
            os.path.join(lx_path, ".dtproject"): config['lx-dtproject'],  # .dtproject files
            os.path.join(solution_path, ".dtproject"): config['lx-dtproject'],
            os.path.join(recipe_path, "Dockerfile"): config['dockerfile'],  # Dockerfiles
            os.path.join(recipe_path, "Dockerfile.vnc"): config['dockerfile'],
            os.path.join(recipe_path, "Dockerfile.vscode"): config['dockerfile'],  # Dependencies
            os.path.join(recipe_path, "dependencies-apt.txt"): config["dependencies"],
            os.path.join(recipe_path, "dependencies-py3.txt"): config["dependencies"]
        }  # TODO: Add README, fix apt map
        dtslogger.debug(f"Making the following template updates: {str(file_updates)} ...")

        for file_path, values in file_updates.items():
            fill_template_file(file_path, values)

        dtslogger.info(f"Your LX was created in {create_dir}. For next steps, see the LX Developer Manual.")

    @staticmethod
    def complete(shell, word, line):
        return []
