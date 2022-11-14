import argparse
import logging
import os
from types import SimpleNamespace
from typing import Optional

from utils.docker_utils import get_endpoint_architecture, get_registry_to_use
from utils.duckietown_utils import get_distro_version
from utils.exceptions import ShellNeedsUpdate

# NOTE: this is to avoid breaking the user workspace
try:
    import pydock
except ImportError:
    raise ShellNeedsUpdate("5.2.21")
# NOTE: this is to avoid breaking the user workspace

from dt_shell import DTCommandAbs, dtslogger, DTShell, UserError
from pydock import DockerClient
from utils.dtproject_utils import DTProject


class DTCommand(DTCommandAbs):

    help = 'Runs an instance of VSCode to work on a project'

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-C", "--workdir", default=os.getcwd(),
            help="Directory containing the project to open the editor on"
        )
        # parser.add_argument(
        #     "--pull",
        #     default=False,
        #     action="store_true",
        #     help="Whether to pull the latest VSCode image",
        # )
        parser.add_argument(
            "-u",
            "--username",
            default=os.getlogin(),
            help="The docker registry username to use",
        )
        parser.add_argument(
            "--distro",
            default=None,
            help="Custom distribution to use VSCode from",
        )
        parser.add_argument(
            "--no-build",
            default=False,
            action="store_true",
            help="Whether to skip building VSCode for this project, reuse last build instead",
        )
        parser.add_argument(
            "--recipe",
            default=None,
            help="Path to a custom recipe to use",
        )
        parser.add_argument(
            "--plain",
            default=False,
            action="store_true",
            help="Whether to skip building VSCode for this project, use plain VSCode instead",
        )
        parser.add_argument(
            "-v",
            "--verbose",
            default=False,
            action="store_true",
            help="Be verbose"
        )

        # get pre-parsed or parse arguments
        parsed = kwargs.get("parsed", None)
        if not parsed:
            parsed, remaining = parser.parse_known_args(args=args)
            if remaining:
                dtslogger.warning(f"I do not know about these arguments: {remaining}")
        # ---

        # variables
        registry_to_use = get_registry_to_use()
        debug = dtslogger.level <= logging.DEBUG
        build_args = []

        # show info about project
        parsed.workdir = os.path.abspath(parsed.workdir)
        dtslogger.info("Project workspace: {}".format(parsed.workdir))
        shell.include.devel.info.command(shell, args)
        project = DTProject(parsed.workdir)

        # pick the right architecture
        dtslogger.info("Retrieving info about Docker endpoint...")
        arch: str = get_endpoint_architecture()
        dtslogger.info(f"Target architecture automatically set to {arch}.")

        # recipe
        if parsed.recipe is not None:
            if project.needs_recipe:
                recipe_dir: str = os.path.abspath(parsed.recipe)
                dtslogger.info(f"Using custom recipe from '{recipe_dir}'")
                project.set_recipe_dir(recipe_dir)
            else:
                raise UserError("This project does not support recipes")
        recipe: Optional[DTProject] = project.recipe

        # custom VSCode distro
        if parsed.distro:
            dtslogger.info(f"Using custom distro '{parsed.distro}'")
            build_args.append(("DISTRO", parsed.distro))

        # some projects carry a Dockerfile.vscode and require a custom VSCode image
        if project.vscode_dockerfile is not None and not parsed.plain:
            # make an image name for VSCode
            vscode_image_tag: str = f"{project.safe_version_name}-vscode"
            vscode_image_name: str = project.image(
                arch=arch,
                owner=parsed.username,
                registry=registry_to_use,
                version=vscode_image_tag
            )

            # build vscode (unless skipped)
            if not parsed.no_build:
                dtslogger.info(f"Building VSCode image for project '{project.name}'...")
                buildx_namespace: SimpleNamespace = SimpleNamespace(
                    workdir=parsed.workdir,
                    username=parsed.username,
                    tag=vscode_image_tag,
                    file=project.vscode_dockerfile,
                    recipe=recipe.path if recipe else None,
                    build_arg=build_args,
                    verbose=parsed.verbose,
                    quiet=not parsed.verbose,
                )
                dtslogger.debug(f"Calling 'devel/buildx' with arguments: {str(buildx_namespace)}")
                shell.include.devel.buildx.command(shell, [], parsed=buildx_namespace)
                dtslogger.info(f"VSCode for project '{project.name}' successfully built!")
            else:
                dtslogger.info(f"Skipping build for VSCode, reusing last available build")
        else:
            # use plain VSCode
            distro: str = parsed.distro or get_distro_version(shell)
            tag: str = f"{distro}-{arch}"
            vscode_image_name: str = f"{registry_to_use}/duckietown/dt-vscode:{tag}"
        # we know which VSCode to use
        dtslogger.debug(f"Using VSCode image '{vscode_image_name}'")

        # run VSCode
        vscode_namespace = SimpleNamespace(
            workdir=[parsed.workdir],
            image=vscode_image_name,
            verbose=parsed.verbose,
        )
        dtslogger.debug(f"Calling 'vscode/run' with arguments: {str(vscode_namespace)}")
        shell.include.vscode.run.command(shell, [], parsed=vscode_namespace)

    @staticmethod
    def complete(shell, word, line):
        return []