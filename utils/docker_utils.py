import os
import platform
import re
import subprocess
import traceback
from os.path import expanduser
from typing import Tuple, Optional, Union

# TODO: move away from dockerpy
import docker as dockerOLD
from docker import DockerClient as DockerClientOLD
from docker.errors import NotFound
from dt_shell import dtslogger, UserError
from dt_shell.config import ShellConfig
from dt_shell.env_checks import check_docker_environment
from duckietown_docker_utils import ENV_REGISTRY

from .cli_utils import start_command_in_subprocess
from .misc_utils import parse_version, hide_string
from .networking_utils import get_duckiebot_ip, resolve_hostname
from .progress_bar import ProgressBar

RPI_GUI_TOOLS = "duckietown/rpi-gui-tools:master18"
RPI_DUCKIEBOT_BASE = "duckietown/rpi-duckiebot-base:master18"
RPI_DUCKIEBOT_CALIBRATION = "duckietown/rpi-duckiebot-calibration:master18"
RPI_DUCKIEBOT_ROS_PICAM = "duckietown/rpi-duckiebot-ros-picam:master18"
RPI_ROS_KINETIC_ROSCORE = "duckietown/rpi-ros-kinetic-roscore:master18"
SLIMREMOTE_IMAGE = "duckietown/duckietown-slimremote:testing"
DEFAULT_DOCKER_TCP_PORT = "2375"
DEFAULT_API_TIMEOUT = 240

DEFAULT_MACHINE = "unix:///var/run/docker.sock"
DEFAULT_REGISTRY = "docker.io"
DOCKER_INFO = """
Docker Endpoint:
  Hostname: {Name}
  Operating System: {OperatingSystem}
  Kernel Version: {KernelVersion}
  OSType: {OSType}
  Architecture: {Architecture}
  Total Memory: {MemTotal}
  CPUs: {NCPU}
"""


def get_registry_to_use(quiet: bool = False) -> str:
    docker_registry = os.environ.get(ENV_REGISTRY, DEFAULT_REGISTRY)
    if docker_registry != DEFAULT_REGISTRY and not quiet:
        dtslogger.warning(f"Using custom {ENV_REGISTRY}='{docker_registry}'.")
    return docker_registry


class AuthNotFound(Exception):
    pass


def get_docker_auth_from_env() -> Tuple[str, str]:
    try:
        registry_username = os.environ[f"DOCKER_USERNAME"]
    except KeyError:
        raise AuthNotFound("Cannot find DOCKER_USERNAME in env.")
    try:
        registry_token = os.environ[f"DOCKER_PASSWORD"]
    except KeyError:
        raise AuthNotFound("Cannot find DOCKER_PASSWORD in env.")
    return registry_username, registry_token


def get_endpoint_ncpus(epoint=None):
    client = get_client(epoint)
    epoint_ncpus = 1
    try:
        epoint_ncpus = client.info()["NCPU"]
    except BaseException:
        dtslogger.warning(
            f"Failed to retrieve the number of CPUs on the Docker endpoint. "
            f"Using default value of {epoint_ncpus}."
        )
    return epoint_ncpus


def get_endpoint_architecture_from_client_OLD(client: DockerClientOLD) -> str:
    from .dtproject_utils import CANONICAL_ARCH

    epoint_arch = client.info()["Architecture"]
    if epoint_arch not in CANONICAL_ARCH:
        dtslogger.error(f"Architecture {epoint_arch} not supported!")
        exit(1)
    return CANONICAL_ARCH[epoint_arch]


def get_endpoint_architecture(hostname=None, port=DEFAULT_DOCKER_TCP_PORT) -> str:
    client = (
        dockerOLD.from_env()
        if hostname is None
        else DockerClientOLD(base_url=sanitize_docker_baseurl(hostname, port))
    )
    return get_endpoint_architecture_from_client_OLD(client)


def sanitize_docker_baseurl(baseurl: str, port=DEFAULT_DOCKER_TCP_PORT) -> Optional[str]:
    if baseurl is None:
        return None
    if baseurl.startswith("unix:"):
        return baseurl
    elif baseurl.startswith("tcp://"):
        return resolve_hostname(baseurl)
    else:
        url = resolve_hostname(baseurl)
        if not url.startswith("tcp://"):
            url = f"tcp://{url}"
        if url.count(":") == 1:
            url = f"{url}:{port}"
        return url


def get_client(endpoint=None):
    if endpoint is None:
        client = dockerOLD.from_env(timeout=DEFAULT_API_TIMEOUT)
    else:
        # create client
        client = (
            endpoint
            if isinstance(endpoint, DockerClientOLD)
            else DockerClientOLD(base_url=sanitize_docker_baseurl(endpoint), timeout=DEFAULT_API_TIMEOUT)
        )

    # FIXME: AFD to review
    # AC: Note the client is not registry-specific, don't try to login here.
    # AC: not the place to do it - note that we also would need to login to multiple registries in some cases
    # (try to) login
    # try:
    #     _login_client_OLD(client, registry=registry)
    # except BaseException:
    #     dtslogger.warning(f"An error occurred while trying to login to Docker registry {registry!r}.")
    # # ---
    return client


def get_remote_client(duckiebot_ip: str, port: str = DEFAULT_DOCKER_TCP_PORT) -> DockerClientOLD:
    client = DockerClientOLD(base_url=f"tcp://{duckiebot_ip}:{port}")
    # FIXME: AFD to review
    try:
        env_username, env_password = get_docker_auth_from_env()
    except AuthNotFound:
        pass
    else:
        registry = DEFAULT_REGISTRY
        try:
            _login_client_OLD(client, registry, env_username, env_password, raise_on_error=False)
        except BaseException:
            dtslogger.warning(f"An error occurred while trying to login to Docker registry {registry!r}.")
    return client


def copy_docker_env_into_configuration(
    shell_config: ShellConfig, registry: Optional[str] = None, quiet: bool = False
):
    registry = registry or get_registry_to_use(quiet)
    try:
        env_username, env_password = get_docker_auth_from_env()
    except AuthNotFound:
        pass
    else:
        shell_config.docker_credentials[registry] = {"username": env_username, "secret": env_password}


class CouldNotLogin(Exception):
    pass


def login_client_OLD(client: DockerClientOLD, shell_config: ShellConfig, registry: str, raise_on_error: bool):
    """Raises CouldNotLogin"""
    if registry not in shell_config.docker_credentials:
        msg = f"Cannot find {registry!r} in available config credentials.\n"
        msg += f"I have credentials for {list(shell_config.docker_credentials)}\n"
        msg += (
            f"Use:\n  dts challenges config --docker-server ... --docker-username ... "
            f"--docker-password ...\n"
        )
        msg += "\nfor each of the servers"

        if raise_on_error:
            dtslogger.error(msg)
            raise CouldNotLogin(f"Could not login to {registry!r}.")
        else:
            dtslogger.warn(msg)
            dtslogger.warn("I will try to continue because raise_on_error = False.")

    else:
        reg_credentials = shell_config.docker_credentials[registry]
        docker_username = reg_credentials["username"]
        docker_password = reg_credentials["secret"]

        _login_client_OLD(
            client,
            username=docker_username,
            password=docker_password,
            registry=registry,
            raise_on_error=raise_on_error,
        )


def _login_client_OLD(
    client: DockerClientOLD, registry: str, username: str, password: str, raise_on_error: bool
):
    """Raises CouldNotLogin"""
    password_hidden = hide_string(password)
    dtslogger.info(f"Logging in to {registry} as {username!r} with secret {password_hidden!r}`")
    res = client.login(username=username, password=password, registry=registry, reauth=True)
    dtslogger.debug(f"login response: {res}")
    # Status': 'Login Succeeded'
    if res.get("Status", None) == "Login Succeeded":
        pass
    else:
        if raise_on_error:
            raise CouldNotLogin(f"Could not login to {registry!r}: {res}")
    # TODO: check for error


# TODO quick hack to make this work - duplication of code above bad
def get_endpoint_architecture_from_ip(duckiebot_ip, *, port: str = DEFAULT_DOCKER_TCP_PORT) -> str:
    from .dtproject_utils import CANONICAL_ARCH

    client = get_remote_client(duckiebot_ip=duckiebot_ip, port=port)
    epoint_arch = client.info()["Architecture"]
    if epoint_arch not in CANONICAL_ARCH:
        dtslogger.error(f"Architecture {epoint_arch} not supported!")
        exit(1)
    return CANONICAL_ARCH[epoint_arch]


def pull_image(image: str, endpoint: Union[None, str, "DockerClient"] = None, progress=True):
    client = get_client(endpoint)
    layers = set()
    pulled = set()
    pbar = ProgressBar() if progress else None
    for line in client.api.pull(image, stream=True, decode=True):
        if "id" not in line or "status" not in line:
            continue
        layer_id = line["id"]
        layers.add(layer_id)
        if line["status"] in ["Already exists", "Pull complete"]:
            pulled.add(layer_id)
        # update progress bar
        if progress:
            percentage = max(0.0, min(1.0, len(pulled) / max(1.0, len(layers)))) * 100.0
            pbar.update(percentage)
    if progress:
        pbar.done()


def push_image(image: str, endpoint=None, progress=True) -> str:
    client = get_client(endpoint)

    layers = set()
    pushed = set()
    pbar = ProgressBar() if progress else None
    final_digest = None
    for line in client.api.push(*image.split(":"), stream=True, decode=True):
        if "error" in line:
            l = str(line["error"])
            msg = f"Cannot push image {image}:\n{l}"
            raise Exception(msg)

        if "aux" in line:
            if "Digest" in line["aux"]:
                final_digest = line["aux"]["Digest"]
                continue
        if "id" not in line:
            if "status" in line:
                print(line["status"])
                continue
            continue
        layer_id = line["id"]
        layers.add(layer_id)
        if line["status"] in ["Layer already exists", "Pushed"]:
            pushed.add(layer_id)
        # update progress bar
        if progress:
            percentage = max(0.0, min(1.0, len(pushed) / max(1.0, len(layers)))) * 100.0
            pbar.update(percentage)
    if progress:
        pbar.done()
    if final_digest is None:
        msg = "Expected to get final digest, but none arrived "
        dtslogger.warning(msg)
    else:
        dtslogger.info(f"Push successful - final digest {final_digest}")
    return final_digest


def push_image_to_duckiebot(image_name, hostname):
    # If password required, we need to configure with sshpass
    command = f"docker save {image_name} | gzip | pv | ssh -C duckie@{hostname}.local docker load"
    subprocess.check_output(["/bin/sh", "-c", command])


def logs_for_container(client, container_id):
    logs = ""
    container = client.containers.get(container_id)
    for c in container.logs(stdout=True, stderr=True, stream=True, timestamps=True):
        logs += c.decode("utf-8")
    return logs


def default_env(duckiebot_name, duckiebot_ip):
    return {
        "ROS_MASTER": duckiebot_name,
        "DUCKIEBOT_NAME": duckiebot_name,
        "ROS_MASTER_URI": f"http://{duckiebot_ip}:11311",
        "DUCKIEFLEET_ROOT": "/data/config",
        "DUCKIEBOT_IP": duckiebot_ip,
        "DUCKIETOWN_SERVER": duckiebot_ip,
        "QT_X11_NO_MITSHM": 1,
    }


def run_image_on_duckiebot(image_name, duckiebot_name, env=None, volumes=None):
    duckiebot_ip = get_duckiebot_ip(duckiebot_name)
    duckiebot_client = get_remote_client(duckiebot_ip)
    env_vars = default_env(duckiebot_name, duckiebot_ip)

    if env is not None:
        env_vars.update(env)

    dtslogger.info("Running %s with environment: %s" % (image_name, env_vars))

    params = {
        "image": image_name,
        "remove": True,
        "network_mode": "host",
        "privileged": True,
        "detach": True,
        "environment": env_vars,
    }

    if volumes is not None:
        params["volumes"] = volumes

    # Make sure we are not already running the same image
    if all(elem.image != image_name for elem in duckiebot_client.containers.list()):
        return duckiebot_client.containers.run(**params)
    else:
        dtslogger.warn(
            f"Container with image {image_name} is already running on {duckiebot_name}, skipping..."
        )


def record_bag(duckiebot_name, duration):
    duckiebot_ip = get_duckiebot_ip(duckiebot_name)
    local_client = check_docker_environment()
    dtslogger.info("Starting bag recording...")
    parameters = {
        "image": RPI_DUCKIEBOT_BASE,
        "remove": True,
        "network_mode": "host",
        "privileged": True,
        "detach": True,
        "environment": default_env(duckiebot_name, duckiebot_ip),
        "command": f'bash -c "cd /data && rosbag record --duration {duration} -a"',
        "volumes": bind_local_data_dir(),
    }

    # Mac Docker has ARM support directly in the Docker environment, so we don't need to run qemu...
    if platform.system() != "Darwin":
        parameters["entrypoint"] = "qemu3-arm-static"

    return local_client.containers.run(**parameters)


def run_image_on_localhost(image_name, duckiebot_name, container_name, env=None, volumes=None):
    duckiebot_ip = get_duckiebot_ip(duckiebot_name)
    local_client = check_docker_environment()

    env_vars = default_env(duckiebot_name, duckiebot_ip)

    if env is not None:
        env_vars.update(env)

    try:
        container = local_client.containers.get(container_name)
        dtslogger.info("A container is already running on localhost - stopping it first..")
        stop_container(container)
        remove_container(container)
    except Exception as e:
        dtslogger.warn(f"Could not remove existing container: {e}")

    dtslogger.info(f"Running {image_name} on localhost with environment vars: {env_vars}")

    params = {
        "image": image_name,
        "remove": True,
        "network_mode": "host",
        "privileged": True,
        "detach": True,
        "tty": True,
        "name": container_name,
        "environment": env_vars,
    }

    if volumes is not None:
        params["volumes"] = volumes

    new_local_container = local_client.containers.run(**params)
    return new_local_container


def start_picamera(duckiebot_name):
    duckiebot_ip = get_duckiebot_ip(duckiebot_name)
    duckiebot_client = get_remote_client(duckiebot_ip)
    duckiebot_client.images.pull(RPI_DUCKIEBOT_ROS_PICAM)
    env_vars = default_env(duckiebot_name, duckiebot_ip)

    dtslogger.info(f"Running {RPI_DUCKIEBOT_ROS_PICAM} on {duckiebot_name} with environment vars: {env_vars}")

    return duckiebot_client.containers.run(
        image=RPI_DUCKIEBOT_ROS_PICAM,
        remove=True,
        network_mode="host",
        devices=["/dev/vchiq"],
        detach=True,
        environment=env_vars,
    )


def check_if_running(client: DockerClientOLD, container_name: str):
    try:
        _ = client.containers.get(container_name)
        dtslogger.info(f"{container_name!r} is running.")
        return True
    except Exception as e:
        dtslogger.error(f"{container_name!r} is NOT running - Aborting:\n{e}")
        return False


def remove_if_running(client: DockerClientOLD, container_name: str):
    try:
        container = client.containers.get(container_name)
    except NotFound:
        pass
    else:
        if container.status == "running":
            dtslogger.info(f"Container {container_name} already running - stopping it first..")
            stop_container(container)
        elif container.status == "stopped":
            result = container.wait()
            exit_code = result["StatusCode"]
            if exit_code:
                cmd = f'"docker logs {container_name}'
                msg = (
                    f"Container {container_name} exited with exit code {exit_code}. Consult logs using {cmd} "
                )
                dtslogger.error(msg)
                return
        dtslogger.info(f"Removing container {container_name}")
        try:
            remove_container(container)
        except Exception as e:
            dtslogger.error(f"Could not remove existing container: {e}")


def start_rqt_image_view(duckiebot_name=None):
    dtslogger.info(
        """{}\nOpening a camera feed by running xhost+ and running rqt_image_view...""".format("*" * 20)
    )
    local_client = check_docker_environment()

    local_client.images.pull(RPI_GUI_TOOLS)
    env_vars = {"QT_X11_NO_MITSHM": 1}

    if duckiebot_name is not None:
        duckiebot_ip = get_duckiebot_ip(duckiebot_name)
        env_vars.update(default_env(duckiebot_name, duckiebot_ip))

    operating_system = platform.system()
    if operating_system == "Linux":
        subprocess.call(["xhost", "+"])
        env_vars["DISPLAY"] = ":0"
    elif operating_system == "Darwin":
        IP = subprocess.check_output(
            [
                "/bin/sh",
                "-c",
                "ifconfig en0 | grep inet | awk '$1==\"inet\" {print $2}'",
            ]
        )
        env_vars["IP"] = IP
        subprocess.call(["xhost", "+IP"])

    dtslogger.info(f"Running {RPI_GUI_TOOLS} on localhost with environment vars: {env_vars}")

    return local_client.containers.run(
        image=RPI_GUI_TOOLS,
        remove=True,
        privileged=True,
        detach=True,
        network_mode="host",
        environment=env_vars,
        command='bash -c "source /home/software/docker/env.sh && rqt_image_view"',
    )


def start_gui_tools(duckiebot_name):
    duckiebot_ip = get_duckiebot_ip(duckiebot_name)
    local_client = check_docker_environment()
    operating_system = platform.system()

    local_client.images.pull(RPI_GUI_TOOLS)

    env_vars = default_env(duckiebot_name, duckiebot_ip)
    env_vars["DISPLAY"] = True

    container_name = "gui-tools-interactive"

    if operating_system == "Linux":
        subprocess.call(["xhost", "+"])
        local_client.containers.run(
            image=RPI_GUI_TOOLS,
            network_mode="host",
            privileged=True,
            tty=True,
            name=container_name,
            environment=env_vars,
        )
    elif operating_system == "Darwin":
        IP = subprocess.check_output(
            [
                "/bin/sh",
                "-c",
                "ifconfig en0 | grep inet | awk '$1==\"inet\" {print $2}'",
            ]
        )
        env_vars["IP"] = IP
        subprocess.call(["xhost", "+IP"])
        local_client.containers.run(
            image=RPI_GUI_TOOLS,
            network_mode="host",
            privileged=True,
            tty=True,
            name=container_name,
            environment=env_vars,
        )

    attach_terminal(container_name)


def attach_terminal(container_name, hostname=None):
    if hostname is not None:
        duckiebot_ip = get_duckiebot_ip(hostname)
        docker_attach_command = f"docker -H {duckiebot_ip}:2375 attach {container_name}"
    else:
        docker_attach_command = f"docker attach {container_name}"
    return start_command_in_subprocess(docker_attach_command, os.environ)


def bind_local_data_dir():
    return {"%s/data" % expanduser("~"): {"bind": "/data"}}


def bind_duckiebot_data_dir():
    return {"/data": {"bind": "/data"}}


def bind_avahi_socket():
    return {"/var/run/avahi-daemon/socket": {"bind": "/var/run/avahi-daemon/socket"}}


def stop_container(container):
    try:
        container.stop()
    except Exception as e:
        dtslogger.warn(f"Container {container} not found to stop! {e}")


def remove_container(container):
    try:
        container.remove()
    except Exception as e:
        dtslogger.warn(f"Container {container} not found to remove! {e}")


def pull_if_not_exist(client, image_name):
    from docker.errors import ImageNotFound

    try:
        client.images.get(image_name)
    except ImageNotFound:
        dtslogger.info(f"Image {image_name!r} not found. Pulling from registry.")
        loader = "Downloading ."
        for _ in client.api.pull(image_name, stream=True, decode=True):
            loader += "."
            if len(loader) > 40:
                print(" " * 60, end="\r", flush=True)
                loader = "Downloading ."
            print(loader, end="\r", flush=True)


def build_logs_to_string(build_logs):
    """
    Converts the docker build logs `JSON object
    <https://docker-py.readthedocs.io/en/stable/images.html#docker.models.images.ImageCollection.build>`_
    to a simple printable string.

    Args:
        build_logs: build logs as JSON-decoded objects

    Returns:
        a string with the logs

    """
    s = ""
    for l in build_logs:
        for k, v in l.items():
            if k == "stream":
                s += str(v)
    return s


logger = dtslogger

escape = re.compile("\x1b\[[\d;]*?m")


def remove_escapes(s):
    return escape.sub("", s)


try:
    import dockertown

    _dockertown_available: bool = True
except ImportError:
    dtslogger.warning("Some functionalities are disabled until you update your shell to v5.4.0+")
    _dockertown_available: bool = False


if _dockertown_available:
    from dockertown import DockerClient

    def login_client(client: DockerClient, shell_config: ShellConfig, registry: str, raise_on_error: bool):
        """Raises CouldNotLogin"""
        if registry not in shell_config.docker_credentials:
            msg = f"Cannot find {registry!r} in available config credentials.\n"
            msg += f"I have credentials for {list(shell_config.docker_credentials)}\n"
            msg += (
                f"Use:\n  dts challenges config --docker-server ... --docker-username ... "
                f"--docker-password ...\n"
            )
            msg += "\nfor each of the servers"

            if raise_on_error:
                dtslogger.error(msg)
                raise CouldNotLogin(f"Could not login to {registry!r}.")
            else:
                dtslogger.warn(msg)
                dtslogger.warn("I will try to continue because raise_on_error = False.")

        else:
            reg_credentials = shell_config.docker_credentials[registry]
            docker_username = reg_credentials["username"]
            docker_password = reg_credentials["secret"]

            _login_client(
                client,
                username=docker_username,
                password=docker_password,
                registry=registry,
                raise_on_error=raise_on_error,
            )

    def _login_client(
        client: DockerClient, registry: str, username: str, password: str, raise_on_error: bool = True
    ):
        """Raises CouldNotLogin"""
        password_hidden = hide_string(password)
        dtslogger.info(f"Logging in to {registry} as {username!r} with secret {password_hidden!r}`")
        # noinspection PyBroadException
        try:
            # TODO: add silent=True to dockertown/dockertown
            client.login(server=registry, username=username, password=password)
        except BaseException:
            if raise_on_error:
                traceback.print_exc()
                raise CouldNotLogin(f"Could not login to {registry!r}.")

    def ensure_docker_version(client: DockerClient, v: str):
        version = client.version()
        vnow_str = version["Server"]["Version"]
        vnow = parse_version(vnow_str)
        if v.endswith("+"):
            vneed_str = v.rstrip("+")
            vneed = parse_version(vneed_str)
            if vnow < vneed:
                msg = f"""
    
                Detected Docker Engine {vnow_str} but this command needs Docker Engine >= {vneed_str}.
                Please, update your Docker Engine before continuing.
    
                """
                raise UserError(msg)
        else:
            vneed = parse_version(v)
            if vnow != vneed:
                msg = f"""
    
                Detected Docker Engine {vnow_str} but this command needs Docker Engine == {v}.
                Please, install the correct version before continuing.
    
                """
                raise UserError(msg)
