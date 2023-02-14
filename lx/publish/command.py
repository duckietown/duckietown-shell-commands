import argparse
import os
import shutil
import tempfile
from typing import Optional

from dt_shell import DTCommandAbs, dtslogger, DTShell

from utils.assets_utils import load_template
from utils.dtproject_utils import DTProject
from utils.git_utils import clone_repository, push_repository
from utils.json_schema_form_utils import open_form_from_schema
from utils.template_utils import fill_template_json, fill_template_file, check_dtproject_exists


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

        # Ensure this is an LX template and get dirs
        parsed.workdir = os.path.abspath(parsed.workdir)
        project: DTProject = DTProject(parsed.workdir)
        if not check_dtproject_exists(parsed.workdir, "lx-development"):
            dtslogger.error(f"You need to be in a 'lx-development' project directory to publish with 'dts lx publish'."
                            f"You can generate this type of project with 'dts lx create'.")
        lx_dir: str = os.path.join(parsed.workdir, project.name+"-lx")
        recipe_dir: str = os.path.join(parsed.workdir, project.name+"-recipe")
        solution_dir: str = os.path.join(parsed.workdir, project.name+"-solution")

        svalues: Optional[dict] = open_form_from_schema(
            shell,
            "lx-publish",
            "v3",
            title="Publish your Learning Experience",
            subtitle="Populate the fields below to publish your Learning Experience",
            completion_message="Uploading LX ...\n You can now close this page and return to the terminal."
        )
        svalues["safe_name"] = project.name
        dtslogger.debug(f"Form values received: '{str(svalues)}'")

        # Load in the template configuration and update with user form values
        # The template placeholder values should match the form schema names
        config_raw: dict = load_template("lx", "v3")
        config = fill_template_json(config_raw["publish"], svalues)

        # Verify the project structure - # TODO: currently enforcing created names, is this necessary?
        check_dtproject_exists(parsed.workdir, "lx-development")
        check_dtproject_exists(lx_dir, "template-exercise")
        check_dtproject_exists(recipe_dir, "template-exercise-recipe")
        check_dtproject_exists(solution_dir, "template-exercise")

        # Update the recipe references if necessary
        fill_template_file(os.path.join(parsed.workdir, project.name+"-lx", ".dtproject"), config)

        # Create a .temp dir and clone the current versions of the lx destination repositories
        with tempfile.TemporaryDirectory() as temp_dir:
            lx_dest: str = clone_repository(svalues["lx_repo"], svalues["lx_branch"], temp_dir)
            recipe_dest: str = clone_repository(svalues["recipe_repo"], svalues["recipe_branch"], temp_dir)
            sol_dest: str = clone_repository(svalues["solution_repo"], svalues["solution_branch"], temp_dir)

            # TODO: Update to git diff and apply patch file
            msg: str = svalues["version"] if "version" in svalues.keys() else "Automated commit from dts publish"
            shutil.copytree(lx_dir, lx_dest, dirs_exist_ok=True)
            push_repository(lx_dest, svalues["lx_branch"], msg)
            shutil.copytree(recipe_dir, recipe_dest, dirs_exist_ok=True)
            push_repository(recipe_dest, svalues["recipe_branch"], msg)
            shutil.copytree("solution_dir", "solution_dest", dirs_exist_ok=True)
            push_repository("solution_dest", svalues["solution_branch"], msg)

        # Message success
        dtslogger.info(
            f"\n\n"
            f"==========================================================\n"
            f"|                                                        |\n"
            f"|    Your LX was successfully published'.                |\n"
            f"|                                                        |\n"
            f"|    For next steps, see the LX Developer Manual.        |\n"  # TODO: Link book when live
            f"|                                                        |\n"
            f"==========================================================\n\n"
        )

    @staticmethod
    def complete(shell, word, line):
        return []
