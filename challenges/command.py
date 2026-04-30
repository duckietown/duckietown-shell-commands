import argparse
import copy
import getpass
import json
import os
import random
import tarfile
import tempfile
from datetime import datetime
from typing import Dict, List
from urllib import error as urllib_error
from urllib import request as urllib_request

import yaml
from cli.command import _run_cmd
from dt_shell import DTCommandAbs, DTShell, UserError, dtslogger
from dtproject import DTProject
from utils.challenges_utils import DEFAULT_CHALLENGES_SERVER
from utils.docker_utils import (
    copy_docker_env_into_configuration,
    get_client_OLD,
    get_endpoint_architecture,
    get_registry_to_use,
    login_client_OLD,
    push_image,
)
from utils.duckietown_utils import DEFAULT_OWNER

DEFAULT_CHALLENGES_CLI_IMAGE = "duckietown/duckietown-challenges-cli:ente"
HOST_BUILD_SUBMIT_DISABLE_ENV = "DT_CHALLENGES_DISABLE_HOST_BUILD_SUBMIT"
SHELL_COMMANDS_USER_AGENT = "duckietown-shell-commands"


def _has_option(args: List[str], option: str) -> bool:
    return any(arg == option or arg.startswith(f"{option}=") for arg in args)


def _get_option_value(args: List[str], option: str, default: str = None) -> str:
    for index, arg in enumerate(args):
        if arg == option:
            if index + 1 < len(args):
                return args[index + 1]
            return default
        if arg.startswith(f"{option}="):
            return arg.split("=", 1)[1]
    return default


def _submission_has_image_config(rest: List[str]) -> bool:
    config_path = _get_option_value(rest, "--config", "submission.yaml")
    if not os.path.exists(config_path):
        return False
    try:
        with open(config_path, "rt") as infile:
            data = yaml.safe_load(infile) or {}
    except Exception as e:
        dtslogger.warning(f"Could not inspect submission config '{config_path}': {e}")
        return False
    return bool(data.get("image"))


def _normalize_docker_credentials(credentials_source) -> Dict[str, Dict[str, str]]:
    docker_credentials = {}
    for registry, credentials in credentials_source.items():
        if isinstance(credentials, dict):
            data = copy.deepcopy(credentials)
            if "password" in data and "secret" not in data:
                data["secret"] = data.pop("password")
        else:
            data = {
                "username": getattr(credentials, "username", None),
                "secret": getattr(credentials, "secret", None)
                or getattr(credentials, "password", None),
            }

        if data.get("username") and data.get("secret"):
            docker_credentials[registry] = data

    return docker_credentials


def _get_compatible_docker_credentials(shell: DTShell) -> Dict[str, Dict[str, str]]:
    docker_credentials = _normalize_docker_credentials(
        shell.profile.secrets.docker_credentials
    )
    if docker_credentials:
        return docker_credentials

    return _normalize_docker_credentials(
        getattr(shell.shell_config, "docker_credentials", {})
    )


def _get_submit_registry(server: str, token: str) -> str:
    url = server.rstrip("/") + "/api/registry-info"
    headers = {
        "X-Messaging-Token": token,
        "User-Agent": SHELL_COMMANDS_USER_AGENT,
    }
    request = urllib_request.Request(url, headers=headers, method="GET")
    try:
        with urllib_request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib_error.HTTPError as e:
        details = e.read().decode("utf-8", errors="replace")
        raise UserError(f"Could not query submit registry from {url}: {e}\n\n{details}")
    except urllib_error.URLError as e:
        raise UserError(f"Could not query submit registry from {url}: {e}")

    if (
        not isinstance(payload, dict)
        or not payload.get("ok")
        or "result" not in payload
    ):
        raise UserError(f"Invalid registry-info response from {url}: {payload!r}")

    result = payload["result"]
    if not isinstance(result, dict) or not result.get("registry"):
        raise UserError(f"Invalid registry-info payload from {url}: {result!r}")

    return result["registry"]


def _get_docker_cli_username() -> str:
    try:
        output = _run_cmd(["docker", "info"], get_output=True)
    except BaseException as e:
        dtslogger.debug(f"Could not inspect docker CLI login state: {e}")
        return ""

    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("Username:"):
            return stripped.split(":", 1)[1].strip().lower()

    return ""


def _prepare_host_submit_image(
    shell: DTShell, client, rest: List[str], dt2_token: str
) -> List[str]:
    if os.environ.get(HOST_BUILD_SUBMIT_DISABLE_ENV) == "1":
        return rest
    if _has_option(rest, "--image"):
        return rest
    if _submission_has_image_config(rest):
        return rest

    project = DTProject(os.getcwd())
    arch = get_endpoint_architecture()
    build_args = ["--arch", arch]
    if _has_option(rest, "--no-cache"):
        build_args.append("--no-cache")
    if _has_option(rest, "--buildx"):
        build_args.append("--buildx")

    dtslogger.info(
        "Building submission image on host before invoking the CLI container."
    )
    shell.include.devel.build.command(shell, build_args)

    local_image = project.image(
        arch=arch,
        registry=get_registry_to_use(quiet=True),
        owner=DEFAULT_OWNER,
        version=project.distro,
    )

    registry = _get_submit_registry(os.environ["DTSERVER"], dt2_token)
    docker_credentials = shell.profile.secrets.docker_credentials
    copy_docker_env_into_configuration(
        docker_credentials, registry=registry, quiet=True
    )

    if docker_credentials.contains(registry):
        login_client_OLD(client, docker_credentials, registry, raise_on_error=True)
        owner = docker_credentials.get(registry).username.lower()
    elif registry == "docker.io":
        owner = str(client.info().get("Username") or "").strip().lower()
        if not owner:
            owner = _get_docker_cli_username()
        if not owner:
            raise UserError(
                "No docker.io credentials are stored in dts config and no Docker CLI login was detected."
            )
        dtslogger.info(f"Using existing Docker login for docker.io as '{owner}'.")
    else:
        raise UserError(
            f"Credentials for registry {registry!r} are not available in the current dts profile."
        )

    version = f"submit-{datetime.utcnow():%Y_%m_%d_%H_%M_%S_%f}"
    remote_image = project.image(
        arch=arch,
        registry=registry,
        owner=owner,
        version=version,
    )
    repository, tag = remote_image.rsplit(":", 1)

    dtslogger.info(f"Retagging host-built image {local_image} -> {remote_image}")
    client.images.get(local_image).tag(repository=repository, tag=tag)
    digest = push_image(remote_image, endpoint=client)
    if not digest:
        raise UserError(
            f"Push of {remote_image} completed without returning a registry digest."
        )

    explicit_image = f"{repository}@{digest}"
    dtslogger.info(f"Using host-built submission image {explicit_image}")
    return rest + ["--image", explicit_image]


def _get_logname(user: str, container_name: str) -> str:
    preferred_dir = os.path.join(
        tempfile.gettempdir(),
        user,
        "duckietown",
        "dt-shell-commands",
        "challenges",
    )
    fallback_dir = os.path.join(
        tempfile.gettempdir(),
        f"dt-shell-commands-{user}",
        "challenges",
    )

    for log_dir in (preferred_dir, fallback_dir):
        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError:
            continue

        if os.access(log_dir, os.W_OK | os.X_OK):
            if log_dir != preferred_dir:
                dtslogger.warning(f"Falling back to writable log directory '{log_dir}'")
            return os.path.join(log_dir, f"{container_name}.txt")

    msg = "Could not create a writable log directory for `dts challenges`."
    raise UserError(msg)


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args: List[str]):
        import duckietown_docker_utils.docker_run as docker_run_module
        from duckietown_docker_utils import generic_docker_run

        parser = argparse.ArgumentParser(prog="dts challenges")

        parser.add_argument(
            "-C",
            "--workdir",
            default=None,
            type=str,
            help="Working directory to run the command from",
        )

        parser.add_argument(
            "--image",
            default=DEFAULT_CHALLENGES_CLI_IMAGE,
            help="Which image to use; combine with --no-pull to use an image already available locally",
        )

        parser.add_argument("--entrypoint", default=None)
        parser.add_argument("--shell", default=False, action="store_true")
        parser.add_argument("--root", default=False, action="store_true")
        parser.add_argument("--no-pull", action="store_true", default=False, help="")
        parser.add_argument(
            "--remote-build", action="store_true", default=False, help=""
        )

        parser.add_argument("action", type=str, nargs=1, help="Action to perform")

        # parse everything to find the action
        parsed, _ = parser.parse_known_args(args=args)
        action: str = parsed.action[0]
        # parse everything `challenges [here] <action> ...`
        parsed, _ = parser.parse_known_args(args=args[: args.index(action) + 1])
        rest = args[args.index(action) :]

        if parsed.workdir is not None:
            if not os.path.isdir(parsed.workdir):
                dtslogger.error(
                    f"Path '{parsed.workdir}' does not exist or it is not a directory"
                )
                exit(1)
            # move over to the custom workdir
            os.chdir(parsed.workdir)

        if "DTSERVER" not in os.environ:
            os.environ["DTSERVER"] = DEFAULT_CHALLENGES_SERVER
            dtslogger.info(
                f"Using default Challenges Server {DEFAULT_CHALLENGES_SERVER}"
            )

        # dtslogger.info(str(dict(args=args, parsed=parsed, rest=rest)))
        dt2_token: str = shell.profile.secrets.dt_token
        client = get_client_OLD()

        if action == "submit" and not parsed.remote_build:
            rest = _prepare_host_submit_image(shell, client, rest, dt2_token)

        docker_credentials = _get_compatible_docker_credentials(shell)

        if "DT_MOUNT" in os.environ:
            development = True
        else:
            development = False

        timestamp = "{:%Y_%m_%d_%H_%M_%S_%f}".format(datetime.now())
        container_name = f"challenges_{timestamp}_{random.randint(0, 10)}"
        user = getpass.getuser()
        logname = _get_logname(user, container_name)
        volumes_from = []
        volume_dummy = None
        container_v = None

        if "DOCKER_HOST" in os.environ:
            dtslogger.warning("Using remote build mode because of DOCKER_HOST")
            parsed.remote_build = True

        if parsed.remote_build:
            dummy_container = f"{container_name}_dummy_container"
            volume_name = f"{container_name}_dummy_volume"
            cwd = os.getcwd()
            volume_dummy = client.volumes.create(name=volume_name)
            image_dummy = "alpine:3.4"
            client.images.pull(image_dummy)
            container_v = client.containers.create(
                image=image_dummy,
                volumes=[f"{volume_name}:{cwd}"],
                name=dummy_container,
                command="/bin/true",
            )

            tar = tarfile.open(cwd + ".tar", mode="w")

            list_files = _run_cmd(
                ["git", "ls-tree", "-r", "HEAD", "--name-only"], get_output=True
            )

            filenames = list_files.split("\n")
            try:
                for f in filenames:
                    tar.add(f)

                if os.path.exists(".git"):
                    tar.add(".git")
            finally:
                tar.close()
            tar2 = tarfile.open(cwd + ".tar", mode="r")
            tar2.list()

            data = open(cwd + ".tar", "rb").read()
            dtslogger.info(f"Now uploading data ({len(data)} bytes).")
            ok = container_v.put_archive(cwd, data)
            dtslogger.info(f"ok: {ok}")
            # cmd = "docker", "create", "-v", cwd, '--name', PWD --name configs3 alpine:3.4 /bin/true
            volumes_from.append(f"{dummy_container}:rw")

        token_key_attribute = "DT2_TOKEN_CONFIG_KEY"
        token_key_originals = {}
        token_key_attributes = [
            attribute_name
            for attribute_name in vars(docker_run_module)
            if attribute_name.endswith("_TOKEN_CONFIG_KEY")
        ]
        if token_key_attribute not in token_key_attributes:
            token_key_attributes.append(token_key_attribute)

        for attribute_name in token_key_attributes:
            existed = hasattr(docker_run_module, attribute_name)
            original_value = getattr(docker_run_module, attribute_name, None)
            token_key_originals[attribute_name] = (existed, original_value)
            setattr(docker_run_module, attribute_name, "token_dt2")

        try:
            gdr = generic_docker_run(
                client,
                parsed.root,
                parsed.image,
                development,
                not parsed.no_pull,
                None,
                None,
                rest,
                parsed.shell,
                parsed.entrypoint,
                dt2_token,
                container_name,
                logname,
                read_only=False,
                docker_credentials=docker_credentials,
                volumes_from=volumes_from,
            )
        finally:
            for attribute_name, (
                existed,
                original_value,
            ) in token_key_originals.items():
                if existed:
                    setattr(docker_run_module, attribute_name, original_value)
                else:
                    delattr(docker_run_module, attribute_name)
            if container_v:
                container_v.remove()
            if volume_dummy:
                volume_dummy.remove(force=True)

        if gdr.retcode:
            msg = f"Execution of docker image failed. Return code: {gdr.retcode}."
            msg += f"\n\nThe log is available at {logname}"
            raise UserError(msg)
