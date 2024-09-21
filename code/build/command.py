import argparse
import os
from types import SimpleNamespace

from dt_shell import DTCommandAbs, dtslogger, DTShell, UserError
from dtproject import DTProject
from utils.misc_utils import get_user_login


class DTCommand(DTCommandAbs):
    help = "Builds a Duckietown project into an image"

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        # Get pre-parsed or parse arguments
        parsed = kwargs.get("parsed", None)
        if not parsed:
            parsed = DTCommand.parser.parse_args(args=args)
        else:
            # combine given args with default values
            default_parsed = DTCommand.parser.parse_args(args=[])
            for k, v in parsed.__dict__.items():
                setattr(default_parsed, k, v)
            parsed = default_parsed

        # load project
        parsed.workdir = os.path.abspath(parsed.workdir)
        project = DTProject(parsed.workdir)

        # Make sure the project recipe is present
        if parsed.recipe is not None:
            if project.needs_recipe:
                recipe_dir: str = os.path.abspath(parsed.recipe)
                dtslogger.info(f"Using custom recipe from '{recipe_dir}'")
                project.set_recipe_dir(recipe_dir)
            else:
                raise UserError("This project does not support recipes")
        else:
            if parsed.recipe_version:
                project.set_recipe_version(parsed.recipe_version)
                dtslogger.info(f"Using recipe version on branch '{parsed.recipe_version}'")
            project.ensure_recipe_exists()
            project.ensure_recipe_updated()

        # collect build arguments (if any)
        build_arg = []
        # - launcher
        if parsed.launcher:
            # make sure the launcher exists
            if parsed.launcher not in project.launchers:
                dtslogger.error(f"Launcher '{parsed.launcher}' not found in the current project")
                return False
            build_arg.append(("LAUNCHER", parsed.launcher))

        # Build the project using 'devel buildx' functionality
        buildx_namespace: SimpleNamespace = SimpleNamespace(
            workdir=parsed.workdir,
            machine=parsed.machine,
            username=parsed.username,
            file=project.dockerfile,
            no_cache=parsed.no_cache,
            pull=not parsed.no_pull,
            push=parsed.push,
            recipe=parsed.recipe,
            recipe_version=parsed.recipe_version,
            registry=parsed.registry,
            verbose=parsed.verbose,
            quiet=parsed.quiet,
            build_arg=build_arg,
        )
        dtslogger.debug(f"Building with 'devel/build' using args: {buildx_namespace}")
        return shell.include.devel.build.command(shell, [], parsed=buildx_namespace)

    @staticmethod
    def complete(shell, word, line):
        return []
