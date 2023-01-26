import argparse
import json
import logging
import os
import shutil
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Tuple, List

from dt_shell import DTCommandAbs, DTShell, dtslogger

from utils.cli_utils import check_program_dependency
from utils.docker_utils import get_registry_to_use, get_endpoint_architecture
from utils.dtproject_utils import DTProject
from utils.duckietown_utils import get_distro_version
from utils.exceptions import ShellNeedsUpdate

# NOTE: this is to avoid breaking the user workspace
try:
    import dockertown
except ImportError:
    raise ShellNeedsUpdate("5.4.0+")
# NOTE: this is to avoid breaking the user workspace

DCSS_RSA_SECRET_LOCATION = "secrets/rsa/{dns}/id_rsa"
DCSS_RSA_SECRET_SPACE = "private"
SSH_USERNAME = "duckie"
CONTAINER_RSA_KEY_LOCATION = "/ssh/id_rsa"


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        # Configure args
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-C",
            "--workdir",
            default=os.getcwd(),
            help="Directory containing the book to publish"
        )
        parser.add_argument(
            "--distro",
            default=None,
            help="Which base distro (jupyter-book) to use"
        )
        parser.add_argument(
            "destination",
            type=str,
            nargs=1,
            help="Destination hostname of the website to publish, e.g., 'docs.duckietown.com'"
        )
        # Get pre-parsed or parse arguments
        parsed = kwargs.get("parsed", None)
        if not parsed:
            parsed, _ = parser.parse_known_args(args=args)
        parsed.destination = parsed.destination[0]

        # load project
        parsed.workdir = os.path.abspath(parsed.workdir)
        project: DTProject = DTProject(parsed.workdir)

        # make sure we are building the right project type
        if project.type != "template-book":
            dtslogger.error(f"Project of type '{project.type}' not supported. Only projects of type "
                            f"'template-book' can be cleaned with 'dts docs clean'.")
            return False

        # make sure we support this version of the template
        if project.type_version != "2":
            dtslogger.error(f"Project of type '{project.type}', "
                            f"version '{project.type_version}' not supported.")
            return False

        # variables
        registry_to_use = get_registry_to_use()
        debug = dtslogger.level <= logging.DEBUG
        volumes: List[Tuple[str, str, str]] = []

        # artifacts location
        html_dir: str = os.path.join(project.path, "html")
        pdf_dir: str = os.path.join(project.path, "pdf")

        # book-specific parameters
        SSH_HOSTNAME = f"ssh-{parsed.destination}"
        BOOK_NAME = project.name
        BOOK_BRANCH_NAME = project.version_name

        # custom distro
        if parsed.distro:
            dtslogger.info(f"Using custom distro '{parsed.distro}'")
        else:
            parsed.distro = get_distro_version(shell)

        # create docker client
        docker = dockertown.DockerClient(debug=debug)

        # pick the right architecture
        dtslogger.info("Retrieving info about Docker endpoint...")
        arch: str = get_endpoint_architecture()
        dtslogger.info(f"Target architecture automatically set to {arch}.")

        # use plain JupyterBook
        parsed.distro = parsed.distro or project.distro
        tag: str = f"{parsed.distro}-{arch}"
        jb_image_name: str = f"{registry_to_use}/duckietown/dt-jupyter-book:{tag}"
        dtslogger.debug(f"Using JupyterBook image '{jb_image_name}'")

        # check which artifacts need to be published
        publish_html: bool = os.path.exists(os.path.join(html_dir, "index.html"))
        publish_pdf: bool = os.path.exists(os.path.join(pdf_dir, "book.pdf"))

        if publish_html:
            html_dir: str = os.path.join(project.path, "html")
            volumes.append((html_dir, "/out/html", "rw"))

        if publish_pdf:
            pdf_dir: str = os.path.join(project.path, "pdf")
            volumes.append((pdf_dir, "/out/pdf", "rw"))

        # publish
        with TemporaryDirectory() as tmpdir:
            # download RSA key
            dtslogger.info(f"Downloading RSA key for tunnel '{SSH_HOSTNAME}'...")
            local_rsa = os.path.join(tmpdir, "id_rsa")
            shell.include.data.get.command(
                shell,
                [],
                parsed=SimpleNamespace(
                    file=[local_rsa],
                    object=[DCSS_RSA_SECRET_LOCATION.format(dns=SSH_HOSTNAME)],
                    space=DCSS_RSA_SECRET_SPACE,
                    token=os.environ.get("DUCKIETOWN_CI_DT_TOKEN", None)
                ),
            )
            # setup key permissions
            os.chmod(local_rsa, 0o600)
            # mount key
            volumes.append((local_rsa, CONTAINER_RSA_KEY_LOCATION, "ro"))

            # start the publish process
            dtslogger.info(f"Publishing project '{project.name}'...")
            container_name: str = f"docs-publish-{project.name}"
            args = {
                "image": jb_image_name,
                "remove": True,
                "volumes": volumes,
                "name": container_name,
                "envs": {
                    "DT_LAUNCHER": "publish-artifacts",
                    "SSH_HOSTNAME": SSH_HOSTNAME,
                    "SSH_USERNAME": SSH_USERNAME,
                    "BOOK_NAME": BOOK_NAME,
                    "BOOK_BRANCH_NAME": BOOK_BRANCH_NAME,
                },
                "stream": True
            }
            dtslogger.debug(
                f"Calling docker.run with arguments:\n" f"{json.dumps(args, indent=4, sort_keys=True)}\n"
            )
            logs = docker.run(**args)

            # consume logs
            for (stream, line) in logs:
                line = line.decode("utf-8")
                print(line, end="")

            dtslogger.info(f"Project '{project.name}' published.")

