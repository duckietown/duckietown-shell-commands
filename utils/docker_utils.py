import datetime
import os
import platform
import subprocess
import sys
import time
import traceback
from os.path import expanduser

import six

import docker
from dt_shell import dtslogger
from dt_shell.env_checks import check_docker_environment
from utils.cli_utils import start_command_in_subprocess
from utils.networking_utils import get_duckiebot_ip

RPI_GUI_TOOLS = "duckietown/rpi-gui-tools:master18"
RPI_DUCKIEBOT_BASE = "duckietown/rpi-duckiebot-base:master18"
RPI_DUCKIEBOT_CALIBRATION = "duckietown/rpi-duckiebot-calibration:master18"
RPI_DUCKIEBOT_ROS_PICAM = "duckietown/rpi-duckiebot-ros-picam:master18"
RPI_ROS_KINETIC_ROSCORE = "duckietown/rpi-ros-kinetic-roscore:master18"
SLIMREMOTE_IMAGE = "duckietown/duckietown-slimremote:testing"
DEFAULT_DOCKER_TCP_PORT = '2375'


def get_remote_client(duckiebot_ip, port=DEFAULT_DOCKER_TCP_PORT):
    return docker.DockerClient(base_url=f'tcp://{duckiebot_ip}:{port}')


def continuously_monitor(client, container_name):
    from docker.errors import NotFound, APIError

    dtslogger.debug("Monitoring container %s" % container_name)
    last_log_timestamp = None
    while True:
        try:
            container = client.containers.get(container_name)
        except Exception as e:
            # msg = 'Cannot get container %s: %s' % (container_name, e)
            # dtslogger.info(msg)
            break
            # dtslogger.info('Will wait.')
            # time.sleep(5)
            # continue

        dtslogger.info("status: %s" % container.status)
        if container.status == "exited":
            msg = "The container exited."

            logs = ""
            for c in container.logs(
                stdout=True, stderr=True, stream=True, since=last_log_timestamp
            ):
                last_log_timestamp = datetime.datetime.now()
                logs += c.decode("utf-8")
            dtslogger.error(msg)

            tf = "evaluator.log"
            with open(tf, "w") as f:
                f.write(logs)

            msg = "Logs saved at %s" % tf
            dtslogger.info(msg)

            # return container.exit_code
            return  # XXX
        try:
            for c in container.logs(
                stdout=True,
                stderr=True,
                stream=True,
                follow=True,
                since=last_log_timestamp,
            ):
                if six.PY2 or (type(c) is str):
                    sys.stdout.write(c)
                else:
                    sys.stdout.write(c.decode("utf-8"))
                last_log_timestamp = datetime.datetime.now()

            time.sleep(3)
        except KeyboardInterrupt:
            dtslogger.info("Received CTRL-C. Stopping container...")
            try:
                container.stop()
                dtslogger.info("Removing container")
                container.remove()
                dtslogger.info("Container removed.")
            except NotFound:
                pass
            except APIError as e:
                # if e.errno == 409:
                #
                pass
            break
        except BaseException:
            dtslogger.error(traceback.format_exc())
            dtslogger.info("Will try to re-attach to container.")
            time.sleep(3)
    # dtslogger.debug('monitoring graceful exit')


def push_image_to_duckiebot(image_name, hostname):
    # If password required, we need to configure with sshpass
    command = "docker save %s | gzip | pv | ssh -C duckie@%s.local docker load" % (
        image_name,
        hostname,
    )
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
            "Container with image %s is already running on %s, skipping..."
            % (image_name, duckiebot_name)
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
        dtslogger.info(
            "slim remote already running on %s, restarting..." % duckiebot_name
        )
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

    dtslogger.info(
        "Running %s on localhost with environment vars: %s" % (image_name, env_vars)
    )

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
        "Running %s on %s with environment vars: %s"
        % (RPI_DUCKIEBOT_ROS_PICAM, duckiebot_name, env_vars)
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
        dtslogger.info("%s already running - stopping it first.." % container_name)
        stop_container(container)
        dtslogger.info("removing %s" % container_name)
        remove_container(container)
    except Exception as e:
        dtslogger.warn("couldn't remove existing container: %s" % e)


def start_rqt_image_view(duckiebot_name=None):
    dtslogger.info(
        """{}\nOpening a camera feed by running xhost+ and running rqt_image_view...""".format(
            "*" * 20
        )
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

    dtslogger.info(
        "Running %s on localhost with environment vars: %s" % (RPI_GUI_TOOLS, env_vars)
    )

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
        docker_attach_command = "docker -H %s:2375 attach %s" % (
            duckiebot_ip,
            container_name,
        )
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

        repository = image_name.split(':')[0]
        try:
            tag = image_name.split(':')[1]
        except IndexError:
            tag = 'latest'

        loader = 'Downloading .'
        for _ in client.api.pull(repository, tag, stream=True, decode=True):
            loader += '.'
            if len(loader)>40:
                print(' '*60, end='\r', flush=True)
                loader = 'Downloading .'
            print(loader, end='\r', flush=True)
