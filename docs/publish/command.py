import argparse
import json
import logging
import os
import re
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Tuple, List, Set

from dt_shell import DTCommandAbs, DTShell, dtslogger

from utils.docker_utils import get_registry_to_use, get_endpoint_architecture
from dtproject import DTProject
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
SAFE_BRANCH_REGEX = re.compile("^[a-z]+-staging$")

SUPPORTED_PROJECT_TYPES = {
    "template-book": {"2", },
    "template-library": {"2", },
    "template-basic": {"4", },
}


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
            "--force",
            default=False,
            action="store_true",
            help="Force the action",
        )
        parser.add_argument(
            "destination",
            type=str,
            nargs=1,
            help="Destination hostname of the website to publish, e.g., 'docs.duckietown.com'"
        )

        # get pre-parsed or parse arguments
        parsed = kwargs.get("parsed", None)
        if not parsed:
            parsed = parser.parse_args(args=args)
        parsed.destination = parsed.destination[0]

        # load project
        parsed.workdir = os.path.abspath(parsed.workdir)
        project: DTProject = DTProject(parsed.workdir)

        # make sure we are building the right project type
        if project.type not in SUPPORTED_PROJECT_TYPES:
            dtslogger.error(f"Project of type '{project.type}' not supported. Only projects of type "
                            f"{', '.join(SUPPORTED_PROJECT_TYPES)} can be built with 'dts docs build'.")
            return False
        supported_versions: Set[str] = SUPPORTED_PROJECT_TYPES[project.type]

        # make sure we support this project type version
        if project.type_version not in supported_versions:
            dtslogger.error(f"Project of type '{project.type}' version '{project.type_version}' is "
                            f"not supported. Only versions {', '.join(supported_versions)} are.")
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
        BOOK_NAME = project.name if project.name.startswith("book-") else f"book-{project.name}"
        BOOK_BRANCH_NAME = project.version_name

        # safe branch names
        if not SAFE_BRANCH_REGEX.match(BOOK_BRANCH_NAME) and not parsed.force:
            dtslogger.error(f"Users can only publish branches matching the pattern "
                            f"'{SAFE_BRANCH_REGEX.pattern}', unless forced (--force).")
            exit(1)

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
            dtslogger.info(f"Publishing project '{BOOK_NAME}'...")
            container_name: str = f"docs-publish-{BOOK_NAME}"
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

            published_title: str = BOOK_NAME.replace("book-", "", 1)
            url: str = f"https://{parsed.destination}/{BOOK_BRANCH_NAME}/{published_title}/index.html"
            bar: str = "=" * len(url)
            spc: str = " " * len(url)
            pspc: str = " " * (len(url)-len(BOOK_NAME))
            dtslogger.info(
                f"\n\n"
                f"====================={bar}===========================================\n"
                f"|                    {spc}                                          |\n"
                f"|    Project '{BOOK_NAME}' published to:{pspc}                                  |\n"
                f"|                    {spc}                                          |\n"
                f"|        >   {url}                                                  |\n"
                f"|                    {spc}                                          |\n"
                f"====================={bar}===========================================\n"
            )
