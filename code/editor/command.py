import argparse
import os
from types import SimpleNamespace
from typing import Optional

from utils.docker_utils import get_endpoint_architecture, get_registry_to_use
from utils.duckietown_utils import get_distro_version
from utils.exceptions import ShellNeedsUpdate

# NOTE: this is to avoid breaking the user workspace
try:
    import dockertown
except ImportError:
    raise ShellNeedsUpdate("5.4.0+")
# NOTE: this is to avoid breaking the user workspace

from dt_shell import DTCommandAbs, dtslogger, DTShell, UserError
from utils.dtproject_utils import DTProject
from utils.misc_utils import get_user_login


class DTCommand(DTCommandAbs):

    help = "Runs an instance of VSCode to work on a project"

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-C",
            "--workdir",
            default=os.getcwd(),
            help="Directory containing the project to open the editor on",
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
            default=get_user_login(),
            help="The docker registry username to use",
        )
        parser.add_argument(
            "--distro",
            default=None,
            help="Custom distribution to use VSCode from",
        )
        parser.add_argument(
            "--bind",
            default="127.0.0.1",
            type=str,
            help="Address to bind to",
        )
        parser.add_argument(
            "--no-build",
            default=False,
            action="store_true",
            help="Whether to skip building VSCode for this project, reuse last build instead",
        )
        parser.add_argument(
            "--build-only",
            default=False,
            action="store_true",
            help="Whether to build VSCode for this project without running it",
        )
        parser.add_argument(
            "--recipe",
            type=str,
            default=None,
            help="Path to use if specifying a custom local recipe path",
        )
        parser.add_argument(
            "--recipe-version",
            default=None,
            help="Branch to use if specifying a test branch of the recipes repository",
        )
        parser.add_argument(
            "--image",
            type=str,
            default=None,
            help="Docker image to use as editor (advanced use only)",
        )
        parser.add_argument(
            "--plain",
            default=False,
            action="store_true",
            help="Whether to skip building VSCode for this project, use plain VSCode instead",
        )
        parser.add_argument(
            "--no-pull",
            default=False,
            action="store_true",
            help="Whether to skip updating the base VSCode image from the registry",
        )
        parser.add_argument(
            "--keep",
            default=False,
            action="store_true",
            help="Whether to keep the VSCode once done (useful for debugging)",
        )
        parser.add_argument(
            "--impersonate",
            default=None,
            type=str,
            help="Username or UID of the user to impersonate inside VSCode",
        )
        parser.add_argument("-v", "--verbose", default=False, action="store_true", help="Be verbose")

        # get pre-parsed or parse arguments
        parsed = kwargs.get("parsed", None)
        if not parsed:
            parsed = parser.parse_args(args=args)
        else:
            # combine given args with default values
            default_parsed = parser.parse_args(args=[])
            for k, v in parsed.__dict__.items():
                setattr(default_parsed, k, v)
            parsed = default_parsed
        # ---

        # variables
        registry_to_use = get_registry_to_use()
        build_args = []

        # show info about project
        parsed.workdir = os.path.abspath(parsed.workdir)
        dtslogger.info("Project workspace: {}".format(parsed.workdir))
        shell.include.devel.info.command(shell, args)
        project = DTProject(parsed.workdir)

        # incompatible arguments
        # - --image and --build-only
        if parsed.image and parsed.build_only:
            dtslogger.error("Arguments --image and --build-only are not compatible with each other.")
            exit(1)
        # -  --image and --plain
        if parsed.image and parsed.build_only:
            dtslogger.error("Arguments --image and --plain are not compatible with each other.")
            exit(1)
        # -  --image and --no-build
        if parsed.image and parsed.no_build:
            dtslogger.error("Argument --no-build is implicit when providing a custom editor with --image.")
            exit(1)
        # pick the right architecture
        dtslogger.info("Retrieving info about Docker endpoint...")
        arch: str = get_endpoint_architecture()
        dtslogger.info(f"Target architecture automatically set to {arch}.")

        # find (or build) the vscode image to run
        if parsed.image is not None:
            vscode_image_name: str = parsed.image
            dtslogger.info(f"Using custom image: {vscode_image_name}")
        else:
            # editor not provided, we need to build our own
            # recipe
            if parsed.recipe is not None:
                if project.needs_recipe:
                    recipe_dir: str = os.path.abspath(parsed.recipe)
                    dtslogger.info(f"Using custom recipe from '{recipe_dir}'")
                    project.set_recipe_dir(recipe_dir)
                else:
                    raise UserError("This project does not support recipes")
            else:
                project.ensure_recipe_exists()
                project.ensure_recipe_updated()
            recipe: Optional[DTProject] = project.recipe

            # custom VSCode distro
            if parsed.distro:
                dtslogger.info(f"Using custom distro '{parsed.distro}'")
            else:
                parsed.distro = get_distro_version(shell)
            build_args.append(("DISTRO", parsed.distro))

            # avoid weird silence
            if parsed.build_only and project.vscode_dockerfile is None:
                dtslogger.error("No Dockerfile.vscode found.")
                return False

            # some projects carry a Dockerfile.vscode and require a custom VSCode image
            if (project.vscode_dockerfile is not None) and (not parsed.plain):
                # make an image name for VSCode
                vscode_image_tag: str = f"{project.safe_version_name}-vscode"
                vscode_image_name: str = project.image(
                    arch=arch, owner=parsed.username, registry=registry_to_use, version=vscode_image_tag
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
                        pull=not parsed.no_pull,
                        verbose=parsed.verbose,
                        quiet=not parsed.verbose,
                    )
                    dtslogger.debug(
                        f"Calling command 'devel/buildx' " f"with arguments: {str(buildx_namespace)}"
                    )
                    shell.include.devel.buildx.command(shell, [], parsed=buildx_namespace)
                    dtslogger.info(f"VSCode for project '{project.name}' successfully built!")
                else:
                    if not parsed.build_only:
                        dtslogger.info(f"Skipping build for VSCode, reusing last available build")
            else:
                # use plain VSCode
                tag: str = f"{parsed.distro}-{arch}"
                vscode_image_name: str = f"{registry_to_use}/duckietown/dt-vscode:{tag}"

            # build only stops here
            if parsed.build_only:
                return True

        # we know which VSCode to use
        dtslogger.debug(f"Using VSCode image '{vscode_image_name}'")

        # run VSCode
        vscode_namespace = SimpleNamespace(
            workdir=[parsed.workdir],
            image=vscode_image_name,
            bind=parsed.bind,
            impersonate=parsed.impersonate,
            verbose=parsed.verbose,
            keep=parsed.keep,
        )
        dtslogger.debug(f"Calling 'vscode/run' with arguments: {str(vscode_namespace)}")
        shell.include.vscode.run.command(shell, [], parsed=vscode_namespace)
        return True

    @staticmethod
    def complete(shell, word, line):
        return []
