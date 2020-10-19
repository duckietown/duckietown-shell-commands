import os
import platform
import subprocess
import sys
import re
import time
import traceback
from datetime import datetime
from os.path import expanduser

import docker
from dt_shell import dtslogger
from dt_shell.env_checks import check_docker_environment


from utils.cli_utils import ProgressBar, start_command_in_subprocess
from utils.networking_utils import get_duckiebot_ip

RPI_GUI_TOOLS = "duckietown/rpi-gui-tools:master18"
RPI_DUCKIEBOT_BASE = "duckietown/rpi-duckiebot-base:master18"
RPI_DUCKIEBOT_CALIBRATION = "duckietown/rpi-duckiebot-calibration:master18"
RPI_DUCKIEBOT_ROS_PICAM = "duckietown/rpi-duckiebot-ros-picam:master18"
RPI_ROS_KINETIC_ROSCORE = "duckietown/rpi-ros-kinetic-roscore:master18"
SLIMREMOTE_IMAGE = "duckietown/duckietown-slimremote:testing"
DEFAULT_DOCKER_TCP_PORT = "2375"

DEFAULT_MACHINE = "unix:///var/run/docker.sock"
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


def get_endpoint_architecture(hostname=None, port=DEFAULT_DOCKER_TCP_PORT):
    from utils.dtproject_utils import CANONICAL_ARCH

    client = (
        docker.from_env()
        if hostname is None
        else docker.DockerClient(base_url=sanitize_docker_baseurl(hostname, port))
    )
    epoint_arch = client.info()["Architecture"]
    if epoint_arch not in CANONICAL_ARCH:
        dtslogger.error(f"Architecture {epoint_arch} not supported!")
        exit(1)
    return CANONICAL_ARCH[epoint_arch]


def sanitize_docker_baseurl(baseurl: str, port=DEFAULT_DOCKER_TCP_PORT):
    if baseurl.startswith("unix:"):
        return baseurl
    elif baseurl.startswith("tcp://"):
        return baseurl
    else:
        return f"tcp://{baseurl}:{port}"


def get_client(endpoint=None):
    if endpoint is None:
        return docker.from_env()
    return (
        endpoint
        if isinstance(endpoint, docker.DockerClient)
        else docker.DockerClient(base_url=sanitize_docker_baseurl(endpoint))
    )


def get_remote_client(duckiebot_ip, port=DEFAULT_DOCKER_TCP_PORT):
    return docker.DockerClient(base_url=f"tcp://{duckiebot_ip}:{port}")

# TODO quick hack to make this work - duplication of code above bad
def get_endpoint_architecture_from_ip(duckiebot_ip, port=DEFAULT_DOCKER_TCP_PORT):
    from utils.dtproject_utils import CANONICAL_ARCH
    client = get_remote_client(duckiebot_ip, port)
    epoint_arch = client.info()["Architecture"]
    if epoint_arch not in CANONICAL_ARCH:
        dtslogger.error(f"Architecture {epoint_arch} not supported!")
        exit(1)
    return CANONICAL_ARCH[epoint_arch]

def pull_image(image, endpoint=None, progress=True):
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


def push_image(image, endpoint=None, progress=True, **kwargs):
    client = get_client(endpoint)
    layers = set()
    pushed = set()
    pbar = ProgressBar() if progress else None
    for line in client.api.push(*image.split(":"), stream=True, decode=True, **kwargs):
        if "id" not in line or "status" not in line:
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


def push_image_to_duckiebot(image_name, hostname):
    # If password required, we need to configure with sshpass
    command = "docker save %s | gzip | pv | ssh -C duckie@%s.local docker load" % (image_name, hostname,)
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
        "ROS_MASTER_URI": "http://%s:11311" % duckiebot_ip,
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
            "Container with image %s is already running on %s, skipping..." % (image_name, duckiebot_name)
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
        "command": 'bash -c "cd /data && rosbag record --duration %s -a"' % duration,
        "volumes": bind_local_data_dir(),
    }

    # Mac Docker has ARM support directly in the Docker environment, so we don't need to run qemu...
    if platform.system() != "Darwin":
        parameters["entrypoint"] = "qemu3-arm-static"

    return local_client.containers.run(**parameters)


def start_slimremote_duckiebot_container(duckiebot_name, max_vel):
    duckiebot_ip = get_duckiebot_ip(duckiebot_name)
    duckiebot_client = get_remote_client(duckiebot_ip)

    container_name = "evaluator"
    try:
        container = duckiebot_client.containers.get(container_name)
        dtslogger.info("slim remote already running on %s, restarting..." % duckiebot_name)
        stop_container(container)
        remove_container(container)
    except Exception as e:
        dtslogger.info("Starting slim remote on %s" % duckiebot_name)

    parameters = {
        "image": SLIMREMOTE_IMAGE,
        "remove": True,
        "privileged": True,
        "detach": True,
        "environment": {"DUCKIETOWN_MAXSPEED": max_vel},
        "name": container_name,
        "ports": {"5558": "5558", "8902": "8902"},
    }

    return duckiebot_client.containers.run(**parameters)


def run_image_on_localhost(image_name, duckiebot_name, container_name, env=None, volumes=None):
    duckiebot_ip = get_duckiebot_ip(duckiebot_name)
    local_client = check_docker_environment()

    env_vars = default_env(duckiebot_name, duckiebot_ip)

    if env is not None:
        env_vars.update(env)

    try:
        container = local_client.containers.get(container_name)
        dtslogger.info("an image already on localhost - stopping it first..")
        stop_container(container)
        remove_container(container)
    except Exception as e:
        dtslogger.warn("coulgn't remove existing container: %s" % e)

    dtslogger.info("Running %s on localhost with environment vars: %s" % (image_name, env_vars))

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

    dtslogger.info(
        "Running %s on %s with environment vars: %s" % (RPI_DUCKIEBOT_ROS_PICAM, duckiebot_name, env_vars)
    )

    return duckiebot_client.containers.run(
        image=RPI_DUCKIEBOT_ROS_PICAM,
        remove=True,
        network_mode="host",
        devices=["/dev/vchiq"],
        detach=True,
        environment=env_vars,
    )


def check_if_running(client, container_name):
    try:
        _ = client.containers.get(container_name)
        dtslogger.info("%s is running." % container_name)
        return True
    except Exception as e:
        dtslogger.error("%s is NOT running - Aborting" % e)
        return False


def remove_if_running(client, container_name):
    try:
        container = client.containers.get(container_name)
        dtslogger.info("Container %s already running - stopping it first.." % container_name)
        stop_container(container)
        dtslogger.info("Removing container %s" % container_name)
        remove_container(container)
    except Exception as e:
        dtslogger.warn("Could not remove existing container: %s" % e)


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
            ["/bin/sh", "-c", "ifconfig en0 | grep inet | awk '$1==\"inet\" {print $2}'", ]
        )
        env_vars["IP"] = IP
        subprocess.call(["xhost", "+IP"])

    dtslogger.info("Running %s on localhost with environment vars: %s" % (RPI_GUI_TOOLS, env_vars))

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
            ["/bin/sh", "-c", "ifconfig en0 | grep inet | awk '$1==\"inet\" {print $2}'", ]
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
        docker_attach_command = "docker -H %s:2375 attach %s" % (duckiebot_ip, container_name,)
    else:
        docker_attach_command = "docker attach %s" % container_name
    return start_command_in_subprocess(docker_attach_command, os.environ)


def bind_local_data_dir():
    return {"%s/data" % expanduser("~"): {"bind": "/data"}}


def bind_duckiebot_data_dir():
    return {"/data": {"bind": "/data"}}


def stop_container(container):
    try:
        container.stop()
    except Exception as e:
        dtslogger.warn("Container %s not found to stop! %s" % (container, e))


def remove_container(container):
    try:
        container.remove()
    except Exception as e:
        dtslogger.warn("Container %s not found to remove! %s" % (container, e))


def pull_if_not_exist(client, image_name):
    from docker.errors import ImageNotFound

    try:
        client.images.get(image_name)
    except ImageNotFound:
        dtslogger.info("Image %s not found. Pulling from registry." % (image_name))

        repository = image_name.split(":")[0]
        try:
            tag = image_name.split(":")[1]
        except IndexError:
            tag = "latest"

        loader = "Downloading ."
        for _ in client.api.pull(repository, tag, stream=True, decode=True):
            loader += "."
            if len(loader) > 40:
                print(" " * 60, end="\r", flush=True)
                loader = "Downloading ."
            print(loader, end="\r", flush=True)


def build_if_not_exist(client, image_path, tag):
    from docker.errors import BuildError
    import json

    try:
        # loader = 'Building .'
        for line in client.api.build(
            path=image_path, nocache=True, rm=True, tag=tag, dockerfile=image_path + "/Dockerfile"
        ):
            try:
                sys.stdout.write(json.loads(line.decode("utf-8"))["stream"])
            except Exception:
                pass
    except BuildError as e:
        print("Unable to build, reason: {} ".format(str(e)))


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


IMPORTANT_ENVS = {
    "AIDO_REGISTRY": "docker.io",
    "PIP_INDEX_URL": "https://pypi.org/simple",
    'DTSERVER': "https://challenges.duckietown.org/v4",
}


def replace_important_env_vars(s: str) -> str:
    for vname, vdefault in IMPORTANT_ENVS.items():
        vref = "${%s}" % vname
        if vref in s:
            value = os.environ.get(vname, vdefault)
            s = s.replace(vref, value)
    return s
logger = dtslogger

def continuously_monitor(client, container_name: str, log: str = None):
    if log is None:
        log = f'{container_name}.log'
    from docker.errors import NotFound, APIError

    logger.debug(f"Monitoring container {container_name}; logs at {log}")
    last_log_timestamp = None
    while True:
        try:
            container = client.containers.get(container_name)
        except Exception as e:
            # msg = 'Cannot get container %s: %s' % (container_name, e)
            # logger.info(msg)
            break
            # logger.info('Will wait.')
            # time.sleep(5)
            # continue

        logger.info("status: %s" % container.status)
        if container.status == "exited":
            msg = "The container exited."
            logger.info(msg)

            with open(log, "a") as f:
                for c in container.logs(stdout=True, stderr=True, stream=True, since=last_log_timestamp):
                    last_log_timestamp = datetime.now()
                    log_line = c.decode("utf-8")
                    sys.stderr.write(log_line)
                    f.write(remove_escapes(log_line))

            msg = f"Logs saved at {log}"
            logger.info(msg)

            # return container.exit_code
            return  # XXX
        try:
            with open(log, "a") as f:
                for c in container.logs(
                    stdout=True, stderr=True, stream=True, follow=True, since=last_log_timestamp,
                ):
                    log_line = c.decode("utf-8")
                    sys.stderr.write(log_line)
                    f.write(remove_escapes(log_line))
                    last_log_timestamp = datetime.now()

            time.sleep(3)
        except KeyboardInterrupt:
            logger.info("Received CTRL-C. Stopping container...")
            try:
                logger.info(f"Stopping container {container_name}")
                container.stop()
                logger.info(f"Removing container {container_name}")
                container.remove()
                logger.info(f"Container {container_name} removed.")
            except NotFound:
                pass
            except APIError as e:
                # if e.errno == 409:
                #
                pass
            break
        except BaseException:
            logger.error(traceback.format_exc())
            logger.info("Will try to re-attach to container.")
            time.sleep(3)
    # logger.debug('monitoring graceful exit')


escape = re.compile("\x1b\[[\d;]*?m")


def remove_escapes(s):
    return escape.sub("", s)
