import argparse
import json
import logging
import os
import re
import sys
from dt_data_api import DataClient

from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Tuple, List, Set

from dt_shell import DTCommandAbs, DTShell, dtslogger

from utils.docker_utils import get_registry_to_use, get_endpoint_architecture
from dtproject import DTProject
from dt_shell.exceptions import ShellNeedsUpdate

# NOTE: this is to avoid breaking the user workspace
try:
    import dockertown
except ImportError:
    raise ShellNeedsUpdate("5.4.0+")
# NOTE: this is to avoid breaking the user workspace

DCSS_RSA_SECRET_LOCATION = "secrets/rsa/ssh-{dns}/id_rsa"
DCSS_RSA_SECRET_SPACE = "private"
SSH_USERNAME = "duckie"
SAFE_BRANCH_REGEX = re.compile(r"^[a-z]+-staging$")
# we need the server path since docker in docker - todo automate this
SERVER_PATH = "/home/shared/dt-davinci-deployment/ci.duckietown.com/user-data/workspace"

SUPPORTED_PROJECT_TYPES = {
    "template-book": {
        "2",
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
        # Configure args
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-C", "--workdir", default=os.getcwd(), help="Directory containing the book to publish"
        )
        parser.add_argument("--distro", default=None, help="Which base distro (jupyter-book) to use")
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
            help="Destination hostname of the website to publish, e.g., 'docs.duckietown.com'",
        )
        parser.add_argument("--ci", default=False, action="store_true", help="Are we running on jenkins?")

        # get pre-parsed or parse arguments
        parsed = DTCommand._resolve_parsed(args, kwargs.get("parsed"), parser=parser)
        parsed.destination = parsed.destination[0]

        # load project
        parsed.workdir = os.path.abspath(parsed.workdir)
        project: DTProject = DTProject(parsed.workdir)

        # make sure we are building the right project type
        if project.type not in SUPPORTED_PROJECT_TYPES:
            dtslogger.error(
                f"Project of type '{project.type}' not supported. Only projects of type "
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

        # variables
        registry_to_use = get_registry_to_use()
        debug = dtslogger.level <= logging.DEBUG

        local_html_dir: str = os.path.join(project.path, "html")
        local_pdf_dir: str = os.path.join(project.path, "pdf")

        # if we are running on jenkins it is a docker in docker setup
        # so the result is that we need to mount the directory on the host.
        if parsed.ci:
            project_path = project.path
            path_list = project_path.split("/")
            folder_name = path_list[-1]
            html_dir = os.path.join(SERVER_PATH, folder_name, "html")
            pdf_dir = os.path.join(SERVER_PATH, folder_name, "pdf")
            print("SERVER HTML DIR:" + html_dir)

        else:
            # artifacts location
            html_dir = local_html_dir
            pdf_dir = local_pdf_dir

        dns = parsed.destination
        # book-specific parameters
        SSH_HOSTNAME = f"ssh-{parsed.destination}"
        BOOK_NAME = project.name if project.name.startswith("book-") else f"book-{project.name}"
        BOOK_BRANCH_NAME = project.version_name

        # safe branch names
        if not SAFE_BRANCH_REGEX.match(BOOK_BRANCH_NAME) and not parsed.force:
            dtslogger.error(
                f"Users can only publish branches matching the pattern "
                f"'{SAFE_BRANCH_REGEX.pattern}', unless forced (--force)."
            )
            exit(1)

        # custom distro
        if parsed.distro:
            dtslogger.info(f"Using custom distro '{parsed.distro}'")
        else:
            # the distro is by default the one given by the project, in compatibility mode we use the shell distro
            parsed.distro = project.distro if project.format.version >= 4 else shell.profile.distro.name

        # create docker client
        docker = dockertown.DockerClient(debug=debug)

        # pick the right architecture
        dtslogger.info("Retrieving info about Docker endpoint...")
        arch: str = get_endpoint_architecture()
        dtslogger.info(f"Target architecture automatically set to {arch}.")

        # use plain JupyterBook
        tag: str = f"{parsed.distro}-{arch}"
        jb_image_name: str = f"{registry_to_use}/duckietown/dt-jupyter-book:{tag}"
        dtslogger.debug(f"Using JupyterBook image '{jb_image_name}'")

        # check which artifacts need to be published
        publish_html: bool = os.path.exists(os.path.join(local_html_dir, "index.html"))
        publish_pdf: bool = os.path.exists(os.path.join(local_pdf_dir, "book.pdf"))

        cc_mountpoints = []

        if publish_html:
            cc_mountpoints.append((html_dir, "/out/html", "rw"))

        if publish_pdf:
            cc_mountpoints.append((pdf_dir, "/out/pdf", "rw"))

        # publish
        # download RSA key
        # setup key permissions
        # download RSA key used to publish artifacts
        token = os.environ.get("DUCKIETOWN_CI_DT_TOKEN", None)
        client = DataClient(token)
        storage = client.storage(DCSS_RSA_SECRET_SPACE)
        rsa_key_remote = DCSS_RSA_SECRET_LOCATION.format(dns=dns)
        dtslogger.debug(f"Downloading RSA key from [{DCSS_RSA_SECRET_SPACE}]:{rsa_key_remote}")
        handler = storage.download(rsa_key_remote)
        handler.join()
        dtslogger.info("Download complete!")
        handler.buffer.seek(0)
        rsa_key = handler.buffer.read().decode("utf-8")

        # start the publish process
        dtslogger.info(f"Publishing project '{BOOK_NAME}'...")
        container_name: str = f"docs-publish-{BOOK_NAME}"
        args = {
            "image": jb_image_name,
            "remove": True,
            "volumes": cc_mountpoints,
            "name": container_name,
            "envs": {
                "DEBUG": "1",
                "DT_LAUNCHER": "publish-artifacts",
                "SSH_KEY": rsa_key,
                "LIBRARY_HOSTNAME": dns,
                "LIBRARY_DISTRO": project.distro,
                "SSH_HOSTNAME": SSH_HOSTNAME,
                "SSH_USERNAME": SSH_USERNAME,
                "BOOK_NAME": BOOK_NAME,
                "DT_SUPERUSER": "1",
                "BOOK_BRANCH_NAME": BOOK_BRANCH_NAME,
            },
            "stream": True,
        }
        dtslogger.info(
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
        pspc: str = " " * (len(url) - len(BOOK_NAME))
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
