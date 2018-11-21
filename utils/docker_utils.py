import datetime
import platform
import subprocess
import sys
import time
import traceback

import six

from dt_shell import dtslogger
from dt_shell.env_checks import check_docker_environment

from utils.networking import get_duckiebot_ip

IMAGE_BASE = 'duckietown/rpi-duckiebot-base:master18'
IMAGE_CALIBRATION = 'duckietown/rpi-duckiebot-calibration:master18'
RPI_GUI_TOOLS = 'duckietown/rpi-gui-tools:master18'
RPI_DUCKIEBOT_ROS_PICAM = 'duckietown/rpi-duckiebot-ros-picam:master18'


def get_duckiebot_client(duckiebot_ip):
    import docker
    return docker.DockerClient('tcp://' + duckiebot_ip + ':2375')


def get_local_client():
    import docker
    return docker.from_env()


def continuously_monitor(client, container_name):
    from docker.errors import NotFound, APIError
    dtslogger.debug('Monitoring container %s' % container_name)
    last_log_timestamp = None
    while True:
        try:
            container = client.containers.get(container_name)
        except Exception as e:
            msg = 'Cannot get container %s: %s' % (container_name, e)
            # dtslogger.error(msg)
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
    # If password required, we need to configure with sshass
    command = 'docker save %s | ssh - C duckie@%s.local | docker load' % (image_name, hostname)
    subprocess.check_output(['/bin/sh', '-c', command])


def logs_for_container(client, container_id):
    logs = ''
    container = client.containers.get(container_id)
    for c in container.logs(stdout=True, stderr=True, stream=True, timestamps=True):
        logs += c.decode('utf-8')
    return logs


def start_picamera(duckiebot_name):
    duckiebot_ip = get_duckiebot_ip(duckiebot_name)
    import docker

    local_client = check_docker_environment()
    duckiebot_client = docker.DockerClient('tcp://' + duckiebot_ip + ':2375')

    local_client.images.pull(RPI_GUI_TOOLS)
    duckiebot_client.images.pull(RPI_DUCKIEBOT_ROS_PICAM)

    env_vars = {
        'ROS_MASTER': duckiebot_name,
        'DUCKIEBOT_NAME': duckiebot_name,
        'DUCKIEBOT_IP': duckiebot_ip,
        'QT_X11_NO_MITSHM': 1,
    }

    print("Running with" + str(env_vars))

    duckiebot_client.containers.run(image=RPI_DUCKIEBOT_ROS_PICAM,
                                    network_mode='host',
                                    devices=['/dev/vchiq'],
                                    detach=True,
                                    environment=env_vars)


def view_camera(duckiebot_name):
    duckiebot_ip = get_duckiebot_ip(duckiebot_name)
    import docker

    raw_input("""{}\nWe will now open a camera feed by running xhost+ and opening rqt_image_view...""".format('*' * 20))
    local_client = check_docker_environment()
    duckiebot_client = docker.DockerClient('tcp://' + duckiebot_ip + ':2375')
    operating_system = platform.system()

    local_client.images.pull(RPI_GUI_TOOLS)
    duckiebot_client.images.pull(RPI_DUCKIEBOT_ROS_PICAM)

    env_vars = {
        'ROS_MASTER': duckiebot_name,
        'DUCKIEBOT_NAME': duckiebot_name,
        'DUCKIEBOT_IP': duckiebot_ip,
        'QT_X11_NO_MITSHM': 1,
    }

    print("Running with" + str(env_vars))

    duckiebot_client.containers.run(image=RPI_DUCKIEBOT_ROS_PICAM,
                                    network_mode='host',
                                    devices=['/dev/vchiq'],
                                    detach=True,
                                    environment=env_vars)

    print("Waiting a few seconds for Duckiebot camera container to warm up...")
    time.sleep(3)

    if operating_system == 'Linux':
        subprocess.call(["xhost", "+"])
        env_vars['DISPLAY'] = ':0'
        local_client.containers.run(image=RPI_GUI_TOOLS,
                                    privileged=True,
                                    network_mode='host',
                                    environment=env_vars,
                                    command='bash -c "source /home/software/docker/env.sh && rqt_image_view"')

    elif operating_system == 'Darwin':
        IP = subprocess.check_output(['/bin/sh', '-c', 'ifconfig en0 | grep inet | awk \'$1=="inet" {print $2}\''])
        env_vars['IP'] = IP
        subprocess.call(["xhost", "+IP"])
        local_client.containers.run(image=RPI_GUI_TOOLS,
                                    privileged=True,
                                    network_mode='host',
                                    environment=env_vars,
                                    command='bash -c "source /home/software/docker/env.sh && rqt_image_view"')


def start_gui_tools(duckiebot_name):
    duckiebot_ip = get_duckiebot_ip(duckiebot_name)
    import docker
    local_client = docker.from_env()
    operating_system = platform.system()

    local_client.images.pull(RPI_GUI_TOOLS)

    env_vars = {
        'ROS_MASTER': duckiebot_name,
        'DUCKIEBOT_NAME': duckiebot_name,
        'DUCKIEBOT_IP': duckiebot_ip,
        'QT_X11_NO_MITSHM': True,
        'DISPLAY': True
    }

    if operating_system == 'Linux':
        subprocess.call(["xhost", "+"])
        local_client.containers.run(image=RPI_GUI_TOOLS,
                                    network_mode='host',
                                    privileged=True,
                                    environment=env_vars)
    if operating_system == 'Darwin':
        IP = subprocess.check_output(['/bin/sh', '-c', 'ifconfig en0 | grep inet | awk \'$1=="inet" {print $2}\''])
        env_vars['IP'] = IP
        subprocess.call(["xhost", "+IP"])
        local_client.containers.run(image=RPI_GUI_TOOLS,
                                    network_mode='host',
                                    privileged=True,
                                    environment=env_vars)

    # TODO: attach an interactive TTY
