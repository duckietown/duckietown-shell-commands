import argparse
import json
import logging
import os
from types import SimpleNamespace
from typing import Optional

from dockertown import DockerClient

from dt_shell import DTCommandAbs, DTShell, dtslogger
from dtproject import DTProject
from utils.assets_utils import get_asset_path
from utils.docker_utils import (
    get_endpoint_architecture,
    get_registry_to_use,
    sanitize_docker_baseurl,
)
from utils.misc_utils import sanitize_hostname


# place in the container where the project is installed. Must be in sync with the Dockerfile
CONTAINER_PROJECT_LOCATION = "/project"


class DTCommand(DTCommandAbs):
    help = "Opens the current project in Jupyter Lab"

    requested_stop: bool = False

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parser: argparse.ArgumentParser = DTCommand.parser
        # configure arguments
        parsed, _ = parser.parse_known_args(args=args)
        if "parsed" in kwargs:
            parsed.__dict__.update(kwargs["parsed"].__dict__)
        # ---
        parsed.workdir = os.path.abspath(parsed.workdir)
        project = DTProject(parsed.workdir)

        # create docker client
        debug: bool = dtslogger.level <= logging.DEBUG
        host: Optional[str] = sanitize_docker_baseurl(parsed.machine)
        docker = DockerClient(host=host, debug=debug)

        # get Dockerfile from our assets
        assets_path = get_asset_path("dockerfile", "jupyter-lab", project.type, "v1")
        dockerfile_path = get_asset_path("dockerfile", "jupyter-lab", project.type, "v1", "Dockerfile")

        # sanitize hostname
        if parsed.machine is not None:
            parsed.machine = sanitize_hostname(parsed.machine)

        # pick the right architecture if not set
        if parsed.arch is None:
            parsed.arch = get_endpoint_architecture(parsed.machine)
            dtslogger.info(f"Target architecture automatically set to {parsed.arch}.")

        # make an image name
        image_tag: str = f"{project.safe_version_name}-jupyter-lab"

        # build environment (this is the step that performs the resolution)
        dtslogger.info(
            f"Building jupyter lab environment image for project '{project.name}'..."
        )
        buildx_namespace: SimpleNamespace = SimpleNamespace(
            workdir=parsed.workdir,
            machine=parsed.machine,
            arch=parsed.arch,
            file=dockerfile_path,
            username="duckietown",
            tag=image_tag,
            build_context=[
                ("assets", assets_path),
                ("project", project.path),
            ],
            pull=not parsed.no_pull,
            verbose=parsed.verbose,
            quiet=not parsed.verbose,
            force=True,
        )
        dtslogger.debug(
            f"Calling command 'devel/build' with arguments: {str(buildx_namespace)}"
        )
        shell.include.devel.build.command(shell, [], parsed=buildx_namespace)

        # recreate image name
        registry_to_use = get_registry_to_use()
        image = project.image(
            arch=parsed.arch,
            registry=registry_to_use,
            owner="duckietown",
            extra="jupyter-lab",
            version=project.version_name
        )

        # impersonate
        identity: int = os.getuid()

        # run image
        dtslogger.info(f"Running Jupyter Lab...")
        args = {
            "image": image,
            "remove": True,
            "envs": {
                "IMPERSONATE_UID": identity,
                "JUPYTER_LAB_HOST": parsed.bind,
                "JUPYTER_LAB_PORT": parsed.port,
            },
            "volumes": [(project.path, CONTAINER_PROJECT_LOCATION, "rw")],
            "networks": ["host"]
        }
        dtslogger.debug(
            f"Calling docker.run with arguments:\n"
            f"{json.dumps(args, indent=4, sort_keys=True)}\n"
        )
        docker.run(**args)

    @staticmethod
    def complete(shell, word, line):
        return []
