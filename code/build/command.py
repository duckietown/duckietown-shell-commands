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
        # Configure args
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-C", "--workdir", default=os.getcwd(), help="Directory containing the project to be built"
        )
        parser.add_argument("-H", "--machine", default=None, help="Docker socket or hostname to use")
        parser.add_argument(
            "-u",
            "--username",
            default=get_user_login(),
            help="The docker registry username to use",
        )
        parser.add_argument(
            "--no-pull",
            default=False,
            action="store_true",
            help="Skip updating the base image from the registry",
        )
        parser.add_argument(
            "--no-cache",
            default=False,
            action="store_true",
            help="Ignore the Docker cache"
        )
        parser.add_argument(
            "--push",
            default=False,
            action="store_true",
            help="Push the resulting Docker image to the registry",
        )
        parser.add_argument(
            "--recipe",
            default=None,
            help="Path to use if specifying a custom local recipe path",
        )
        parser.add_argument(
            "--recipe-version",
            default=None,
            help="Branch to use if specifying a test branch of the recipes repository",
        )
        parser.add_argument(
            "--registry",
            default=None,
            help="Docker registry to use",
        )
        parser.add_argument(
            "-L",
            "--launcher",
            default=None,
            help="The launcher to use as entrypoint to the built container",
        )
        parser.add_argument(
            "-b",
            "--base-tag",
            default=None,
            help="Docker tag for the base image. Use when the base image is also a development version",
        )
        parser.add_argument("-v", "--verbose", default=False, action="store_true", help="Be verbose")
        parser.add_argument("--quiet", default=False, action="store_true", help="Be quiet")

        # Get pre-parsed or parse arguments
        parsed = kwargs.get("parsed", None)
        if not parsed:
            parsed = parser.parse_args(args=args)
        else:
            # combine given args with default values
            default_parsed = parser.parse_args(args=[])
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
        dtslogger.debug(f"Building with 'devel/buildx' using args: {buildx_namespace}")
        return shell.include.devel.buildx.command(shell, [], parsed=buildx_namespace)

    @staticmethod
    def complete(shell, word, line):
        return []
