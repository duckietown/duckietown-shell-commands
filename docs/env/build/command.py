import argparse
import os
from types import SimpleNamespace

from dt_shell import DTCommandAbs, DTShell, dtslogger

from utils.docker_utils import get_endpoint_architecture
from utils.dtproject_utils import DTProject
from utils.duckietown_utils import get_distro_version
from utils.exceptions import ShellNeedsUpdate

# NOTE: this is to avoid breaking the user workspace
try:
    import dockertown
except ImportError:
    raise ShellNeedsUpdate("5.4.0+")
# NOTE: this is to avoid breaking the user workspace


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-C",
            "--workdir",
            default=os.getcwd(),
            help="Directory containing the book to work on",
        )
        parser.add_argument(
            "--distro",
            default=None,
            help="Which base distro (jupyter-book) to use"
        )
        parser.add_argument(
            "--no-pull",
            default=False,
            action="store_true",
            help="Whether to skip updating the base image from the registry",
        )
        parser.add_argument("-v", "--verbose", default=False, action="store_true", help="Be verbose")
        # parse arguments

        # Get pre-parsed or parse arguments
        parsed = kwargs.get("parsed", None)
        if not parsed:
            parsed, _ = parser.parse_known_args(args=args)

        # variables
        build_args = []

        # load project
        parsed.workdir = os.path.abspath(parsed.workdir)
        project: DTProject = DTProject(parsed.workdir)

        # make sure we are building the right project type
        if project.type != "template-book":
            dtslogger.error(f"Project of type '{project.type}' not supported. Only projects of type "
                            f"'template-book' can be built with 'dts docs env build'.")
            return False
        if project.type_version != "2":
            dtslogger.error(f"Project of type version '{project.type_version}' not supported. "
                            f"Only projects of type version '2' can be built with 'dts docs env build'.")
            return False

        # pick the right architecture
        dtslogger.info("Retrieving info about Docker endpoint...")
        arch: str = get_endpoint_architecture()
        dtslogger.info(f"Target architecture automatically set to {arch}.")

        # custom distro
        if parsed.distro:
            dtslogger.info(f"Using custom distro '{parsed.distro}'")
        else:
            parsed.distro = get_distro_version(shell)
        build_args.append(("DISTRO", parsed.distro))

        # make an image name for JB
        jb_image_tag: str = f"{project.safe_version_name}-env"

        # build jb environment
        dtslogger.info(f"Building environment image for project '{project.name}'...")
        buildx_namespace: SimpleNamespace = SimpleNamespace(
            workdir=parsed.workdir,
            username="duckietown",
            tag=jb_image_tag,
            build_arg=build_args,
            pull=not parsed.no_pull,
            verbose=parsed.verbose,
            quiet=not parsed.verbose,
            force=True,
            no_login=True
        )
        dtslogger.debug(
            f"Calling command 'devel/buildx' with arguments: {str(buildx_namespace)}"
        )
        shell.include.devel.buildx.command(shell, [], parsed=buildx_namespace)
        dtslogger.info(f"Environment for project '{project.name}' successfully built!")
