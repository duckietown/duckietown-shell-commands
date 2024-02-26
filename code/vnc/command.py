import argparse
import os
from types import SimpleNamespace
from typing import Optional

from utils.docker_utils import get_endpoint_architecture, get_registry_to_use
from dt_shell.exceptions import ShellNeedsUpdate

# NOTE: this is to avoid breaking the user workspace
try:
    import dockertown
except ImportError:
    raise ShellNeedsUpdate("5.4.0+")
# NOTE: this is to avoid breaking the user workspace

from dt_shell import DTCommandAbs, dtslogger, DTShell, UserError
from dtproject import DTProject
from utils.misc_utils import get_user_login


class DTCommand(DTCommandAbs):

    help = "Builds an instance of VNC to work on a project"

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-C",
            "--workdir",
            default=os.getcwd(),
            help="Directory containing the project to build the desktop for",
        )
        # parser.add_argument(
        #     "--pull",
        #     default=False,
        #     action="store_true",
        #     help="Whether to pull the latest VNC image",
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
            help="Custom distribution to use VNC from",
        )
        parser.add_argument(
            "--no-build",
            default=False,
            action="store_true",
            help="Whether to skip building VNC for this project, reuse last build instead",
        )
        parser.add_argument(
            "--build-only",
            default=False,
            action="store_true",
            help="Whether to build VSCode for this project without running it",
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
            help="Whether to skip building VNC for this project, use plain VNC instead",
        )
        parser.add_argument(
            "--impersonate",
            default=None,
            type=str,
            help="Username or UID of the user to impersonate inside VNC",
        )
        parser.add_argument("-v", "--verbose", default=False, action="store_true", help="Be verbose")
        parser.add_argument("--quiet", default=False, action="store_true", help="Be quiet")

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
        if not parsed.quiet:
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
        else:
            project.ensure_recipe_exists()
            project.ensure_recipe_updated()
        recipe: Optional[DTProject] = project.recipe

        # custom VNC distro
        if parsed.distro:
            dtslogger.info(f"Using custom distro '{parsed.distro}'")
        else:
            parsed.distro = shell.profile.distro.name
        build_args.append(("DISTRO", parsed.distro))

        # avoid weird silence
        if parsed.build_only and project.vnc_dockerfile is None:
            dtslogger.error("No Dockerfile.vnc found.")
            return

        # some projects carry a Dockerfile.vnc and require a custom VNC image
        if (project.vnc_dockerfile is not None) and (not parsed.plain):
            # make an image name for VNC
            vnc_image_tag: str = f"{project.safe_version_name}-vnc"
            vnc_image_name: str = project.image(
                arch=arch, owner=parsed.username, registry=registry_to_use, version=vnc_image_tag
            )

            # build vnc (unless skipped)
            if not parsed.no_build:
                dtslogger.info(f"Building VNC image for project '{project.name}'...")
                buildx_namespace: SimpleNamespace = SimpleNamespace(
                    workdir=parsed.workdir,
                    username=parsed.username,
                    tag=vnc_image_tag,
                    file=project.vnc_dockerfile,
                    recipe=recipe.path if recipe else None,
                    build_arg=build_args,
                    verbose=parsed.verbose,
                    quiet=not parsed.verbose,
                )
                dtslogger.debug(f"Calling command 'devel/build' " f"with arguments: {str(buildx_namespace)}")
                shell.include.devel.build.command(shell, [], parsed=buildx_namespace)
                dtslogger.info(f"VNC for project '{project.name}' successfully built!")
            else:
                if not parsed.build_only:
                    dtslogger.info(f"Skipping build for VNC, reusing last available build")
        else:
            # use plain VNC
            tag: str = f"{parsed.distro}-{arch}"
            vnc_image_name: str = f"{registry_to_use}/duckietown/dt-vnc:{tag}"

        # build only stops here
        if parsed.build_only:
            return True

        # we know which VNC to use
        dtslogger.debug(f"Using VNC image '{vnc_image_name}'")

        raise NotImplementedError("dts/vnc/run is not implemented.")

        # # run VNC
        # vnc_namespace = SimpleNamespace(
        #     workdir=[parsed.workdir],
        #     image=vnc_image_name,
        #     impersonate=parsed.impersonate,
        #     verbose=parsed.verbose,
        # )
        # dtslogger.debug(f"Calling 'vnc/run' with arguments: {str(vnc_namespace)}")
        # shell.include.vnc.run.command(shell, [], parsed=vnc_namespace)
        # return True

    @staticmethod
    def complete(shell, word, line):
        return []
