import argparse
import os
import tempfile
from types import SimpleNamespace

from dt_shell import DTCommandAbs, DTShell, dtslogger

from utils.docker_utils import get_endpoint_architecture
from utils.dtproject_utils import DTProject
from utils.duckietown_utils import get_distro_version


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
            "-H",
            "--machine",
            default=None,
            help="Docker socket or hostname where to build the image"
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
        parser.add_argument(
            "--embed",
            default=False,
            action="store_true",
            help="Whether to embed the book source into the image",
        )
        parser.add_argument("-v", "--verbose", default=False, action="store_true", help="Be verbose")

        # Get pre-parsed or parse arguments
        parsed = kwargs.get("parsed", None)
        if not parsed:
            parsed, _ = parser.parse_known_args(args=args)
        else:
            # combine given args with default values
            default_parsed = parser.parse_args(args=[])
            for k, v in parsed.__dict__.items():
                setattr(default_parsed, k, v)
            parsed = default_parsed

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

        # by default, we don't add any source to the image
        source_dir = tempfile.TemporaryDirectory()
        source_path: str = source_dir.name
        if parsed.embed:
            source_path = project.path

        # build jb environment
        dtslogger.info(f"Building environment image for project '{project.name}'...")
        buildx_namespace: SimpleNamespace = SimpleNamespace(
            workdir=parsed.workdir,
            machine=parsed.machine,
            username="duckietown",
            tag=jb_image_tag,
            build_arg=build_args,
            build_context=[("source", source_path)],
            pull=not parsed.no_pull,
            verbose=parsed.verbose,
            quiet=not parsed.verbose,
            force=True,
            no_login=True
        )
        dtslogger.debug(f"Calling command 'devel/buildx' with arguments: {str(buildx_namespace)}")
        shell.include.devel.buildx.command(shell, [], parsed=buildx_namespace)
        # cleanup temporary directory
        source_dir.cleanup()
        # ---
        dtslogger.info(f"Environment for project '{project.name}' successfully built!")
