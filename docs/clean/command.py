import argparse
import json
import logging
import os
import shutil
from typing import Tuple, List

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

CONTAINER_BUILD_CACHE_DIR = "/tmp/jb"
HOST_BUILD_CACHE_DIR = "/tmp/duckietown/docs/{book}"


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        # Configure args
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-C", "--workdir", default=os.getcwd(), help="Directory containing the book to clean"
        )

        # Get pre-parsed or parse arguments
        parsed = kwargs.get("parsed", None)
        if not parsed:
            parsed, _ = parser.parse_known_args(args=args)

        # load project
        parsed.workdir = os.path.abspath(parsed.workdir)
        project: DTProject = DTProject(parsed.workdir)

        # make sure we are building the right project type
        if project.type != "template-book":
            dtslogger.error(f"Project of type '{project.type}' not supported. Only projects of type "
                            f"'template-book' can be cleaned with 'dts docs clean'.")
            return False

        # clean V1
        if project.type_version == "1":
            return clean_v1(shell, args)

        # clean V1
        elif project.type_version == "2":
            return clean_v2(shell, args)

        else:
            dtslogger.error(f"Project of type '{project.type}', "
                            f"version '{project.type_version}' not supported.")
            return False


def clean_v2(shell: DTShell, args):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-C",
        "--workdir",
        default=os.getcwd(),
        help="Directory containing the book to clean",
    )
    parser.add_argument(
        "--image",
        default=None,
        help="Which environment image to use to clean the book"
    )
    parser.add_argument(
        "--distro",
        default=None,
        help="Which base distro (jupyter-book) to use"
    )
    parser.add_argument(
        "--pdf",
        default=False,
        action="store_true",
        help="Whether to clean the PDF instead of HTML",
    )
    parser.add_argument("-v", "--verbose", default=False, action="store_true", help="Be verbose")
    # parse arguments
    parsed = parser.parse_args(args=args)

    # variables
    registry_to_use = get_registry_to_use()
    debug = dtslogger.level <= logging.DEBUG
    volumes: List[Tuple[str, str, str]] = []

    # load project
    parsed.workdir = os.path.abspath(parsed.workdir)
    project: DTProject = DTProject(parsed.workdir)

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
    tag: str = f"{parsed.distro}-{arch}"
    jb_image_name: str = f"{registry_to_use}/duckietown/dt-jupyter-book:{tag}"
    dtslogger.debug(f"Using JupyterBook image '{jb_image_name}'")

    # clean HTML or PDF
    clean_pdf: bool = parsed.pdf
    clean_html: bool = not parsed.pdf

    if clean_html:
        html_dir: str = os.path.join(project.path, "html")
        volumes.append((html_dir, "/out/html", "rw"))

    if clean_pdf:
        pdf_dir: str = os.path.join(project.path, "pdf")
        volumes.append((pdf_dir, "/out/pdf", "rw"))

    # build cache
    build_cache: str = HOST_BUILD_CACHE_DIR.format(book=project.name)
    if os.path.exists(build_cache):
        volumes.append((build_cache, CONTAINER_BUILD_CACHE_DIR, "rw"))

    # start the clean process
    dtslogger.info(f"Cleaning project '{project.name}'...")
    container_name: str = f"docs-clean-{project.name}"
    args = {
        "image": jb_image_name,
        "remove": True,
        "volumes": volumes,
        "name": container_name,
        "envs": {
            "DT_LAUNCHER": "jb-clean"
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
        if stream == "stdout":
            print(line, end="")
        elif parsed.verbose:
            dtslogger.error(line)

    dtslogger.info(f"Project '{project.name}' is now clean.")


def clean_v1(shell: DTShell, args):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-C",
        "--workdir",
        default=os.getcwd(),
        help="Directory containing the book to clean",
    )
    parsed = parser.parse_args(args=args)
    # ---
    outdir = os.path.join(parsed.workdir, "out")
    if os.path.exists(outdir):
        shutil.rmtree(outdir)
        print("Cleaned intermediate results.")
    else:
        print("No intermediate results found.")
    outdir = os.path.join(parsed.workdir, "duckuments-dist")
    if os.path.exists(outdir):
        shutil.rmtree(outdir)
        print("Cleaned output artifacts.")
    else:
        print("No artifacts found.")
