import datetime
import os
import platform
import subprocess
import sys
import time
import traceback
from os.path import expanduser

import docker
import six
from dt_shell import dtslogger
from dt_shell.env_checks import check_docker_environment

from utils.cli_utils import start_command_in_subprocess
from utils.networking_utils import get_duckiebot_ip

RPI_GUI_TOOLS = 'duckietown/rpi-gui-tools:master18'
RPI_DUCKIEBOT_BASE = 'duckietown/rpi-duckiebot-base:master18'
RPI_DUCKIEBOT_CALIBRATION = 'duckietown/rpi-duckiebot-calibration:master18'
RPI_DUCKIEBOT_ROS_PICAM = 'duckietown/rpi-duckiebot-ros-picam:master18'
RPI_ROS_KINETIC_ROSCORE = 'duckietown/rpi-ros-kinetic-roscore:master18'
SLIMREMOTE_IMAGE = 'duckietown/duckietown-slimremote'


def get_remote_client(duckiebot_ip):
    return docker.DockerClient('tcp://' + duckiebot_ip + ':2375')


def continuously_monitor(client, container_name):
    from docker.errors import NotFound, APIError
    dtslogger.debug('Monitoring container %s' % container_name)
    last_log_timestamp = None
    while True:
        try:
            container = client.containers.get(container_name)
        except Exception as e:
            msg = 'Cannot get container %s: %s' % (container_name, e)
            dtslogger.error(msg)
            break
            # dtslogger.info('Will wait.')
            # time.sleep(5)
            # continue

        dtslogger.info('status: %s' % container.status)
        if container.status == 'exited':

            msg = 'The container exited.'

            logs = ''
            for c in container.logs(stdout=True, stderr=True, stream=True, since=last_log_timestamp):
                last_log_timestamp = datetime.datetime.now()
                logs += c.decode()
            dtslogger.error(msg)

            tf = 'evaluator.log'
            with open(tf, 'w') as f:
                f.write(logs)

            msg = 'Logs saved at %s' % tf
            dtslogger.info(msg)

            # return container.exit_code
            return  # XXX
        try:
            for c in container.logs(stdout=True, stderr=True, stream=True, follow=True, since=last_log_timestamp):
                if six.PY2:
                    sys.stdout.write(c)
                else:
                    sys.stdout.write(c.decode('utf-8'))

                last_log_timestamp = datetime.datetime.now()

            time.sleep(3)
        except KeyboardInterrupt:
            dtslogger.info('Received CTRL-C. Stopping container...')
            try:
                container.stop()
                dtslogger.info('Removing container')
                container.remove()
                dtslogger.info('Container removed.')
            except NotFound:
                pass
            except APIError as e:
                # if e.errno == 409:
                #
                pass
            break
        except BaseException:
            dtslogger.error(traceback.format_exc())
            dtslogger.info('Will try to re-attach to container.')
            time.sleep(3)
    dtslogger.debug('monitoring graceful exit')


def push_image_to_duckiebot(image_name, hostname):
    # If password required, we need to configure with sshpass
    command = 'docker save %s | gzip | ssh -C duckie@%s.local docker load' % (image_name, hostname)
    subprocess.check_output(['/bin/sh', '-c', command])


def logs_for_container(client, container_id):
    logs = ''
    container = client.containers.get(container_id)
    for c in container.logs(stdout=True, stderr=True, stream=True, timestamps=True):
        logs += c.decode('utf-8')
    return logs


def default_env(duckiebot_name, duckiebot_ip):
    return {'ROS_MASTER': duckiebot_name,
            'DUCKIEBOT_NAME': duckiebot_name,
            'DUCKIEBOT_IP': duckiebot_ip}


def run_image_on_duckiebot(image_name, duckiebot_name):
    duckiebot_ip = get_duckiebot_ip(duckiebot_name)
    duckiebot_client = get_remote_client(duckiebot_ip)
    env_vars = default_env(duckiebot_name, duckiebot_ip)

    dtslogger.info("Running %s with environment: %s" % (image_name, env_vars))

    # Make sure we are not already running the same image
    if all(elem.image != image_name for elem in duckiebot_client.containers.list()):
        return duckiebot_client.containers.run(image=image_name,
                                               remove=True,
                                               network_mode='host',
                                               privileged=True,
                                               detach=True,
                                               environment=env_vars)
    else:
        dtslogger.warn('Container with image %s is already running on %s, skipping...' % (image_name, duckiebot_name))


def record_bag(duckiebot_name, duration):
    duckiebot_ip = get_duckiebot_ip(duckiebot_name)
    local_client = check_docker_environment()
    dtslogger.info("Starting bag recording...")
    parameters = {
        'image': RPI_DUCKIEBOT_BASE,
        'remove': True,
        'network_mode': 'host',
        'privileged': True,
        'detach': True,
        'environment': default_env(duckiebot_name, duckiebot_ip),
        'command': 'bash -c "cd /data && rosbag record --duration %s -a"' % duration,
        'datavol': setup_local_data_volume()
    }

    # Mac Docker has ARM support directly in the Docker environment, so we don't need to run qemu...
    if platform.system() != 'Darwin':
        parameters['entrypoint'] = 'qemu3-arm-static'

    local_client.containers.run(**parameters)


def start_slimremote_duckiebot_container(duckiebot_name):
    duckiebot_ip = get_duckiebot_ip(duckiebot_name)
    duckiebot_client = get_remote_client(duckiebot_ip)
    env_vars = default_env(duckiebot_name, duckiebot_ip)
    parameters = {
        'image': RPI_DUCKIEBOT_BASE,
        'remove': True,
        'network_mode': 'host',
        'privileged': True,
        'detach': True,
        'ports': {'5558': '5558', '8902': '8902'},
        'environment': env_vars,
    }

    return duckiebot_client.containers.run(**parameters)


def run_image_on_localhost(image_name, duckiebot_name):
    run_image_on_duckiebot(RPI_ROS_KINETIC_ROSCORE, duckiebot_name)

    duckiebot_ip = get_duckiebot_ip(duckiebot_name)

    local_client = check_docker_environment()

    env_vars = default_env(duckiebot_name, duckiebot_ip)

    dtslogger.info("Running %s on localhost with environment vars: %s" % (image_name, env_vars))

    # Make sure we are not already running this image
    if all(elem.image != image_name for elem in local_client.containers.list()):
        return local_client.containers.run(image=image_name,
                                           remove=True,
                                           network_mode='host',
                                           privileged=True,
                                           detach=True,
                                           environment=env_vars)
    else:
        dtslogger.warn('Container with image %s is already running on %s, skipping...' % (image_name, duckiebot_name))


def start_picamera(duckiebot_name):
    duckiebot_ip = get_duckiebot_ip(duckiebot_name)

    duckiebot_client = get_remote_client(duckiebot_ip)

    duckiebot_client.images.pull(RPI_DUCKIEBOT_ROS_PICAM)

    env_vars = default_env(duckiebot_name, duckiebot_ip)

    dtslogger.info("Running %s on %s with environment vars: %s" % (RPI_DUCKIEBOT_ROS_PICAM, duckiebot_name, env_vars))

    return duckiebot_client.containers.run(image=RPI_DUCKIEBOT_ROS_PICAM,
                                           remove=True,
                                           network_mode='host',
                                           devices=['/dev/vchiq'],
                                           detach=True,
                                           environment=env_vars)


def start_rqt_image_view(duckiebot_name=None):
    dtslogger.info("""{}\nOpening a camera feed by running xhost+ and running rqt_image_view...""".format('*' * 20))
    local_client = check_docker_environment()

    local_client.images.pull(RPI_GUI_TOOLS)
    env_vars = {'QT_X11_NO_MITSHM': 1}

    if duckiebot_name is not None:
        duckiebot_ip = get_duckiebot_ip(duckiebot_name)
        env_vars.update({'DUCKIEBOT_NAME': duckiebot_name, 'ROS_MASTER': duckiebot_name, 'DUCKIEBOT_IP': duckiebot_ip})

    operating_system = platform.system()
    if operating_system == 'Linux':
        subprocess.call(["xhost", "+"])
        env_vars['DISPLAY'] = ':0'
    elif operating_system == 'Darwin':
        IP = subprocess.check_output(['/bin/sh', '-c', 'ifconfig en0 | grep inet | awk \'$1=="inet" {print $2}\''])
        env_vars['IP'] = IP
        subprocess.call(["xhost", "+IP"])

    dtslogger.info("Running %s on localhost with environment vars: %s" % (RPI_GUI_TOOLS, env_vars))

    return local_client.containers.run(image=RPI_GUI_TOOLS,
                                       remove=True,
                                       privileged=True,
                                       network_mode='host',
                                       environment=env_vars,
                                       command='bash -c "source /home/software/docker/env.sh && rqt_image_view"')


def start_gui_tools(duckiebot_name):
    duckiebot_ip = get_duckiebot_ip(duckiebot_name)
    local_client = check_docker_environment()
    operating_system = platform.system()

    local_client.images.pull(RPI_GUI_TOOLS)

    env_vars = {
        'ROS_MASTER': duckiebot_name,
        'DUCKIEBOT_NAME': duckiebot_name,
        'DUCKIEBOT_IP': duckiebot_ip,
        'QT_X11_NO_MITSHM': True,
        'DISPLAY': True
    }

    container_name = 'gui-tools-interactive'

    if operating_system == 'Linux':
        subprocess.call(["xhost", "+"])
        local_client.containers.run(image=RPI_GUI_TOOLS,
                                    network_mode='host',
                                    privileged=True,
                                    tty=True,
                                    name=container_name,
                                    environment=env_vars)
    elif operating_system == 'Darwin':
        IP = subprocess.check_output(['/bin/sh', '-c', 'ifconfig en0 | grep inet | awk \'$1=="inet" {print $2}\''])
        env_vars['IP'] = IP
        subprocess.call(["xhost", "+IP"])
        local_client.containers.run(image=RPI_GUI_TOOLS,
                                    network_mode='host',
                                    privileged=True,
                                    tty=True,
                                    name=container_name,
                                    environment=env_vars)

    attach_terminal(container_name)


def attach_terminal(container_name, hostname=None):
    duckiebot_ip = get_duckiebot_ip(hostname)
    if hostname is not None:
        docker_attach_command = 'docker -H %s:2375 attach %s' % (duckiebot_ip, container_name)
    else:
        docker_attach_command = 'docker attach %s' % container_name
    return start_command_in_subprocess(docker_attach_command, os.environ)


def setup_local_data_volume():
    return {'%s/data' % expanduser("~"): {'bind': '/data'}}


def setup_duckiebot_data_volume():
    return {'/data': {'bind': '/data'}}
