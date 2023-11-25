import argparse
import os
import tempfile
from types import SimpleNamespace
from typing import Set, Optional

from dt_shell import DTCommandAbs, DTShell, dtslogger

from utils.assets_utils import get_asset_path
from utils.docker_utils import get_endpoint_architecture
from dtproject import DTProject

SUPPORTED_PROJECT_TYPES = {
    "template-book": {
        "2", "4",
    },
    "template-library": {
        "2",
    },
    "template-basic": {
        "4",
    },
    "template-ros": {
        "4",
    },
}


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
            "-H", "--machine", default=None, help="Docker socket or hostname where to build the image"
        )
        parser.add_argument("--distro", default=None, help="Which base distro (jupyter-book) to use")
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
        if project.type not in SUPPORTED_PROJECT_TYPES:
            dtslogger.error(
                f"Project of type '{project.type}' not supported. Only projects of types "
                f"{', '.join(SUPPORTED_PROJECT_TYPES)} can be built with 'dts docs build'."
            )
            return False
        supported_versions: Set[str] = SUPPORTED_PROJECT_TYPES[project.type]

        # make sure we support this project type version
        if project.type_version not in supported_versions:
            dtslogger.error(
                f"Project of type '{project.type}' version '{project.type_version}' is "
                f"not supported. Only versions {', '.join(supported_versions)} are."
            )
            return False

        # pick the right architecture
        dtslogger.info("Retrieving info about Docker endpoint...")
        arch: str = get_endpoint_architecture(parsed.machine)
        dtslogger.info(f"Target architecture automatically set to {arch}.")

        # the distro is by default the one given by the project, in compatibility mode we use the shell distro
        DEFAULT_LIBRARY_DISTRO = project.distro if project.format.version >= 4 else shell.profile.distro.name

        # custom distro
        if parsed.distro:
            dtslogger.info(f"Using custom distro '{parsed.distro}'")
        else:
            # default distro
            parsed.distro = DEFAULT_LIBRARY_DISTRO
        build_args.append(("DISTRO", parsed.distro))

        # make an image name for JB
        jb_image_tag: str = f"{project.distro}-env"

        # by default, we don't add any source to the image
        source_dir = tempfile.TemporaryDirectory()
        source_path: str = source_dir.name
        dockerfile_path: Optional[str] = None

        if parsed.embed:
            source_path: str = project.path

        # some projects store their books in subdirectories
        docs_path: str = project.docs_path()
        if docs_path != project.path:
            dockerfile_path = os.path.join(docs_path, "Dockerfile")
            if not os.path.exists(dockerfile_path):
                # provide a Dockerfile if the documentation dir does not carry its own
                dockerfile_path = get_asset_path(
                    "dockerfile", "jupyter-book", project.type, "v1", "Dockerfile"
                )
            if parsed.embed:
                source_path = docs_path

        # build jb environment
        dtslogger.info(f"Building environment image for project '{project.name}'...")
        buildx_namespace: SimpleNamespace = SimpleNamespace(
            workdir=parsed.workdir,
            machine=parsed.machine,
            file=dockerfile_path,
            username="duckietown",
            tag=jb_image_tag,
            build_arg=build_args,
            build_context=[
                ("source", source_path),
                ("project", project.path),
            ],
            pull=not parsed.no_pull,
            verbose=parsed.verbose,
            quiet=not parsed.verbose,
            force=True,
        )
        dtslogger.debug(f"Calling command 'devel/build' with arguments: {str(buildx_namespace)}")
        shell.include.devel.build.command(shell, [], parsed=buildx_namespace)
        # cleanup temporary directory
        source_dir.cleanup()
        # ---
        dtslogger.info(f"Environment for project '{project.name}' successfully built!")
