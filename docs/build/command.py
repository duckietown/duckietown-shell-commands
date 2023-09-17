import argparse
import json
import logging
import os
import re
import sys
from types import SimpleNamespace
from typing import Tuple, List, Optional, Set

from dt_data_api import DataClient
from dt_shell import DTCommandAbs, DTShell, dtslogger

from update import DISTRO
from utils.docker_utils import get_registry_to_use, get_endpoint_architecture, sanitize_docker_baseurl, \
    get_cloud_builder
from dtproject import DTProject
from utils.duckietown_utils import get_distro_version
from utils.exceptions import ShellNeedsUpdate

# NOTE: this is to avoid breaking the user workspace
try:
    import dockertown
except ImportError:
    raise ShellNeedsUpdate("5.4.0+")
# NOTE: this is to avoid breaking the user workspace

from dockertown import DockerClient

CONTAINER_HTML_DIR = "tmp/jb/_build/html"
CONTAINER_PDF_DIR = "tmp/jb/_build/pdf"
CONTAINER_BUILD_CACHE_DIR = "/tmp/jb"
HOST_BUILD_CACHE_DIR = "/tmp/duckietown/docs/{book}"

DCSS_RSA_SECRET_LOCATION = "secrets/rsa/ssh-{dns}/id_rsa"
DCSS_RSA_SECRET_SPACE = "private"
SSH_USERNAME = "duckie"
CLOUD_BUILD_ARCH = "amd64"

DEFAULT_LIBRARY_HOSTNAME = "staging-docs.duckietown.com"
DEFAULT_LIBRARY_DISTRO = DISTRO

SUPPORTED_PROJECT_TYPES = {
    "template-book": {"2", "4"},
    "template-library": {"2", },
    "template-basic": {"4", },
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
            "-H",
            "--machine",
            default=None,
            help="Docker socket or hostname where to build the book"
        )
        parser.add_argument(
            "--image",
            default=None,
            help="Which environment image to use to build the book. By default, one will be built."
        )
        parser.add_argument(
            "--distro",
            default=None,
            help="Which base distro (jupyter-book) to use"
        )
        parser.add_argument(
            "--no-build",
            default=False,
            action="store_true",
            help="Whether to skip building the environment for this project, reuse last build instead",
        )
        parser.add_argument(
            "--build-only",
            default=False,
            action="store_true",
            help="Whether to build the environment for this project without running it",
        )
        parser.add_argument(
            "--no-cache",
            default=False,
            action="store_true",
            help="Whether to ignore existing build cache",
        )
        parser.add_argument(
            "--plain",
            default=False,
            action="store_true",
            help="Whether to skip building the environment for this project, use plain JB instead",
        )
        parser.add_argument(
            "--ci",
            default=False,
            action="store_true",
            help="Configure the build for CI",
        )
        parser.add_argument(
            "--publish",
            type=str,
            default=None,
            help="Destination hostname of the website to publish, e.g., 'docs.duckietown.com'",
        )
        parser.add_argument(
            "--library",
            type=str,
            default=DEFAULT_LIBRARY_HOSTNAME,
            help="Hostname of the website hosting the library to link to, e.g., 'docs.duckietown.com'",
        )
        parser.add_argument(
            "--no-pull",
            default=False,
            action="store_true",
            help="Whether to skip updating the base image from the registry",
        )
        parser.add_argument(
            "--pdf",
            default=False,
            action="store_true",
            help="Whether to build a PDF instead of HTML",
        )
        parser.add_argument(
            "--optimize",
            default=False,
            action="store_true",
            help="Whether to run the image optimization step",
        )
        parser.add_argument("-v", "--verbose", default=False, action="store_true", help="Be verbose")

        # get pre-parsed or parse arguments
        parsed = kwargs.get("parsed", None)
        if not parsed:
            parsed = parser.parse_args(args=args)

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
            dtslogger.error(
                "Argument --no-build is implicit when providing a custom environment with --image.")
            exit(1)
        # -  --machine and not --ci
        if parsed.machine and not parsed.ci:
            dtslogger.error("Argument --machine can only be used together with --ci.")
            exit(1)
        # -  --ci and not --publish
        if parsed.ci and parsed.publish is None:
            dtslogger.error("Argument --ci can only be used together with --publish.")
            exit(1)

        # variables
        registry_to_use = get_registry_to_use()
        debug = dtslogger.level <= logging.DEBUG
        build_args = []
        mount_flags = lambda f: ",".join([f] + (["cached"] if sys.platform == "darwin" else []))

        # load project
        parsed.workdir = os.path.abspath(parsed.workdir)
        project: DTProject = DTProject(parsed.workdir)

        # use a cloud machine to build
        if parsed.ci:
            parsed.machine = get_cloud_builder(CLOUD_BUILD_ARCH)

        # create docker client
        host: Optional[str] = sanitize_docker_baseurl(parsed.machine)
        docker = DockerClient(host=host, debug=debug)

        # pick the right architecture
        dtslogger.info("Retrieving info about Docker endpoint...")
        arch: str = get_endpoint_architecture(parsed.machine)
        dtslogger.info(f"Target architecture automatically set to {arch}.")

        # find (or build) the book environment image to run
        if parsed.image is not None:
            # custom JB given, just use it
            jb_image_name: str = parsed.image
            dtslogger.info(f"Using custom image: {jb_image_name}")
        else:
            # JB environment not provided, we need to build our own (unless --plain)
            # custom distro
            if parsed.distro:
                dtslogger.info(f"Using custom distro '{parsed.distro}'")
            else:
                # TODO: this should be the distro of the shell profile instead
                parsed.distro = get_distro_version(shell)
            build_args.append(("DISTRO", parsed.distro))

            # we can use the plain `jupyter-book` environment
            if not parsed.plain:
                # make an image name for JB
                jb_image_tag: str = f"{project.safe_version_name}-env"
                jb_image_name: str = project.image(
                    arch=arch, owner="duckietown", registry=registry_to_use, version=jb_image_tag
                )

                # build jb (unless skipped)
                if not parsed.no_build:
                    shell.include.docs.env.build.command(shell, args=[], parsed=SimpleNamespace(
                        workdir=parsed.workdir,
                        machine=parsed.machine,
                        distro=parsed.distro,
                        embed=parsed.ci,
                        no_pull=parsed.no_pull,
                        verbose=parsed.verbose,
                    ))
                else:
                    if not parsed.build_only:
                        dtslogger.info(
                            f"Skipping environment build for '{project.name}', reusing last available")
            else:
                # use plain JupyterBook
                tag: str = f"{parsed.distro}-{arch}"
                jb_image_name: str = f"{registry_to_use}/duckietown/dt-jupyter-book:{tag}"

            # build only stops here
            if parsed.build_only:
                return True

        # we know which JupyterBook to use
        dtslogger.debug(f"Using JupyterBook image '{jb_image_name}'")

        if not parsed.ci:
            # locations of interest
            html_dir: str = os.path.join(project.path, "html")
            pdf_dir: str = os.path.join(project.path, "pdf")

            # some projects store their books in subdirectories
            book_dir = project.docs_path()

            # collect volumes to mount
            volumes: List[Tuple[str, str, str]] = [
                # source files
                (book_dir, "/book", "ro"),
            ]

            # build HTML
            build_pdf: bool = parsed.pdf
            build_html: bool = True
            if build_html:
                volumes.append((html_dir, "/out/html", mount_flags("rw")))
            # build PDF
            if build_pdf:
                volumes.append((pdf_dir, "/out/pdf", mount_flags("rw")))

            # build cache
            if not parsed.no_cache:
                build_cache: str = HOST_BUILD_CACHE_DIR.format(book=project.name)
                try:
                    os.makedirs(build_cache, exist_ok=True)
                except Exception:
                    pass
                if os.path.exists(build_cache):
                    volumes.append((build_cache, CONTAINER_BUILD_CACHE_DIR, mount_flags("rw")))

            # log reader from container
            def consume_container_logs(_logs):
                # consume logs
                for (stream, line) in _logs:
                    line = line.decode("utf-8")
                    print(line, end="")

            # start the book build process
            dtslogger.info(f"Building project '{project.name}'...")
            container_name: str = f"docs-build-{project.name}"
            args = {
                "image": jb_image_name,
                "remove": True,
                "user": f"{os.getuid()}:{os.getgid()}",
                "envs": {
                    "BOOK_BRANCH_NAME": project.version_name,
                    "LIBRARY_HOSTNAME": parsed.library,
                    "LIBRARY_DISTRO": DEFAULT_LIBRARY_DISTRO,
                    "DEBUG": "1" if debug else "0",
                    "PRODUCTION_BUILD": "0"
                },
                "volumes": volumes,
                "name": container_name,
                "stream": True
            }
            dtslogger.debug(
                f"Calling docker.run with arguments:\n" f"{json.dumps(args, indent=4, sort_keys=True)}\n"
            )
            logs = docker.run(**args)
            consume_container_logs(logs)

            # start the image optimizer process
            if build_html and parsed.optimize:
                dtslogger.info(f"Optimizing media...")
                container_name: str = f"docs-image-optimizer-{project.name}"
                args = {
                    "image": jb_image_name,
                    "remove": True,
                    "user": f"{os.getuid()}:{os.getuid()}",
                    "volumes": volumes,
                    "envs": {
                        "DT_LAUNCHER": "jb-optimize-images",
                        "DEBUG": "1" if debug else "0"
                    },
                    "name": container_name,
                    "stream": True,
                }
                dtslogger.debug(
                    f"Calling docker.run with arguments:\n" f"{json.dumps(args, indent=4, sort_keys=True)}\n"
                )
                logs = docker.run(**args)
                consume_container_logs(logs)

            # print HTML location
            if build_html:
                loc: str = os.path.abspath(html_dir)
                bar: str = "=" * len(loc)
                spc: str = " " * len(loc)
                dtslogger.info(
                    f"\n\n"
                    f"====================={bar}=====\n"
                    f"|                    {spc}    |\n"
                    f"|    HTML artifacts: {loc}    |\n"
                    f"|                    {spc}    |\n"
                    f"====================={bar}=====\n"
                )

            # print PDF location
            if build_pdf:
                loc: str = os.path.abspath(os.path.join(pdf_dir, "book.pdf"))
                bar: str = "=" * len(loc)
                spc: str = " " * len(loc)
                dtslogger.info(
                    f"\n\n"
                    f"==================={bar}=====\n"
                    f"|                  {spc}    |\n"
                    f"|    PDF artifact: {loc}    |\n"
                    f"|                  {spc}    |\n"
                    f"==================={bar}=====\n"
                )
        else:
            # CI build includes: build HTML, build PDF, image optimization, and artifacts publish
            dns = parsed.publish

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

            # get distro from branch name
            library_distro, *_ = re.split(r"[^a-z]+", project.version_name)
            production_build: bool = library_distro == project.version_name

            # define ssh configuration
            ssh_hostname = f"ssh-{dns}"

            # log reader from container
            def consume_container_logs(_logs):
                # consume logs
                for (stream, line) in _logs:
                    line = line.decode("utf-8")
                    print(line, end="")

            # start the book build process
            dtslogger.info(f"Building project '{project.name}'...")
            args = {
                "image": jb_image_name,
                "remove": True,
                "envs": {
                    "DEBUG": "1",
                    "SSH_KEY": rsa_key,
                    "SSH_HOSTNAME": ssh_hostname,
                    "SSH_USERNAME": SSH_USERNAME,
                    "BOOK_NAME": project.name,
                    "BOOK_BRANCH_NAME": project.version_name,
                    "LIBRARY_HOSTNAME": dns,
                    "LIBRARY_DISTRO": library_distro,
                    "DT_LAUNCHER": "ci-build",
                    "PRODUCTION_BUILD": str(int(production_build))
                },
                "stream": True
            }
            dtslogger.debug(
                f"Calling docker.run with arguments:\n" f"{json.dumps(args, indent=4, sort_keys=True)}\n"
            )
            logs = docker.run(**args)
            consume_container_logs(logs)
