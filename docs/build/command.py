import argparse
import getpass
import json
import logging
import os
import subprocess
import sys
from types import SimpleNamespace
from typing import Tuple, List, Optional

from dt_data_api import DataClient
from dt_shell import DTCommandAbs, DTShell, dtslogger
from dt_shell.env_checks import check_docker_environment
from duckietown_docker_utils import ENV_REGISTRY, replace_important_env_vars

from utils.docker_utils import get_registry_to_use, get_endpoint_architecture, sanitize_docker_baseurl
from utils.dtproject_utils import DTProject, get_cloud_builder
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


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        # Configure args
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-C",
            "--workdir",
            default=os.getcwd(),
            help="Directory containing the book to be build"
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
                            f"'template-book' can be built with 'dts docs build'.")
            return False

        # build V1
        if project.type_version == "1":
            return build_v1(shell, args)

        # build V1
        elif project.type_version == "2":
            return build_v2(shell, args)

        else:
            dtslogger.error(f"Project of type '{project.type}', "
                            f"version '{project.type_version}' not supported.")
            return False


def build_v2(shell: DTShell, args):
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
        "--no-optimization",
        default=False,
        action="store_true",
        help="Whether to skip the images optimization step",
    )
    parser.add_argument("-v", "--verbose", default=False, action="store_true", help="Be verbose")
    # parse arguments
    parsed = parser.parse_args(args=args)

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
        dtslogger.error("Argument --no-build is implicit when providing a custom environment with --image.")
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
                    dtslogger.info(f"Skipping environment build for '{project.name}', reusing last available")
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
        volumes: List[Tuple[str, str, str]] = [
            # source files
            (project.path, "/book", "ro"),
        ]

        # build HTML
        build_pdf: bool = parsed.pdf
        build_html: bool = True
        if build_html:
            volumes.append((html_dir, "/out/html", "rw"))
        # build PDF
        if build_pdf:
            volumes.append((pdf_dir, "/out/pdf", "rw"))

        # build cache
        build_cache: str = HOST_BUILD_CACHE_DIR.format(book=project.name)
        try:
            os.makedirs(build_cache, exist_ok=True)
        except Exception:
            pass
        if os.path.exists(build_cache):
            volumes.append((build_cache, CONTAINER_BUILD_CACHE_DIR, "rw"))

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
            "user": f"{os.getuid()}:{os.getuid()}",
            "envs": {
                "BOOK_BRANCH_NAME": project.version_name,
                "DEBUG": "1" if debug else "0"
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
        if build_html and (not parsed.no_optimization):
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
                "DT_LAUNCHER": "ci-build"
            },
            "stream": True
        }
        dtslogger.debug(
            f"Calling docker.run with arguments:\n" f"{json.dumps(args, indent=4, sort_keys=True)}\n"
        )
        logs = docker.run(**args)
        consume_container_logs(logs)


def build_v1(_: DTShell, args):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-C",
        "--workdir",
        default=os.getcwd(),
        help="Directory containing the book to clean",
    )
    parser.add_argument(
        "--image", default="${%s}/duckietown/docs-build:daffy" % ENV_REGISTRY, help="Which image to use"
    )
    parsed = parser.parse_args(args=args)
    # ---
    parsed.workdir = os.path.realpath(parsed.workdir)
    check_docker_environment()

    image = replace_important_env_vars(parsed.image)

    user = getpass.getuser()

    uid1 = os.getuid()

    if sys.platform == "darwin":
        flag = ":delegated"
    else:
        flag = ""

    cache = f"/tmp/{user}/cache"
    if not os.path.exists(cache):
        os.makedirs(cache)

    cmd = [
        "docker",
        "run",
        "-e",
        "USER=%s" % user,
        "-e",
        "USERID=%s" % uid1,
        # '-m', '4GB',
        "--user",
        "%s" % uid1,
        "-e",
        "COMPMAKE_COMMAND=rparmake",
        "-it",
        "-v",
        f"{parsed.workdir}:/pwd{flag}",
        "--workdir",
        "/pwd",
        image,
    ]

    dtslogger.info("executing:\nls " + " ".join(cmd))

    try:
        p = subprocess.Popen(
            cmd,
            bufsize=0,
            executable=None,
            stdin=None,
            stdout=None,
            stderr=None,
            preexec_fn=None,
            shell=False,
            cwd=parsed.workdir,
            env=None,
        )
    except OSError as e:
        if e.errno == 2:
            msg = 'Could not find "docker" executable.'
            DTCommandAbs.fail(msg)
        raise

    p.communicate()
    dtslogger.info("\n\nCompleted.")


def system_cmd_result(pwd, cmd):
    s = subprocess.check_output(cmd, cwd=pwd)
    return s.decode("utf-8")
