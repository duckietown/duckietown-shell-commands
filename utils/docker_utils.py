import datetime
import sys
import time
import traceback


import six

from dt_shell import dtslogger

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


def logs_for_container(client, container_id):
    logs = ''
    container = client.containers.get(container_id)
    for c in container.logs(stdout=True, stderr=True, stream=True, timestamps=True):
        logs += c.decode('utf-8')
    return logs
