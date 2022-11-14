import argparse
import logging
import os
from typing import Optional

from dt_shell import DTCommandAbs, dtslogger, DTShell, UserError

from utils.dtproject_utils import DTProject
from utils.recipe_utils import clone_recipe, update_recipe


class DTCommand(DTCommandAbs):

    help = "Builds a Duckietown exercise into an image"

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        # Configure args
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-C", "--workdir", default=os.getcwd(), help="Directory containing the project to be built"
        )
        parser.add_argument(
            "--recipe",
            default=None,
            help="Path to use if specifying a custom recipe",
        )
        parser.add_argument("-v", "--verbose", default=False, action="store_true", help="Be verbose")

        # Get pre-parsed or parse arguments
        parsed = kwargs.get("parsed", None)
        if not parsed:
            parsed, remaining = parser.parse_known_args(args=args)
            if remaining:
                dtslogger.warning(f"I do not know about these arguments: {remaining}")

        # Show dtproject info (TODO: repeated by buildx call?)
        parsed.workdir = os.path.abspath(parsed.workdir)
        dtslogger.info("Project workspace: {}".format(parsed.workdir))
        shell.include.devel.info.command(shell, args)
        project = DTProject(parsed.workdir)

        # Get the recipe info
        if parsed.recipe is not None:
            if project.needs_recipe:
                recipe_dir: str = os.path.abspath(parsed.recipe)
                dtslogger.info(f"Using custom recipe from '{recipe_dir}'")
                project.set_recipe_dir(recipe_dir)
            else:
                raise UserError("This project does not support recipes")
        recipe: Optional[DTProject] = project.recipe

        # Update/clone recipe repository if necessary
        # TODO: Detangle project and recipe utils
        try:
            update_recipe(repository, branch, location)
        except UserError as e:
            dtslogger.info(f"'{str(e)}'. Attempting to clone the repository now.")
            clone_recipe(repository, branch, location)

        # Build the project using 'devel buildx' functionality
        dtslogger.debug(f"Building with 'devel/buildx' using args: {str(buildx_namespace)}")
        shell.include.devel.buildx.command(shell, args + [""])
        # buildx handles showing project info and assumed recipe support

    @staticmethod
    def complete(shell, word, line):
        return []
