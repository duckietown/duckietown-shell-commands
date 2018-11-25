from __future__ import print_function

import argparse
import datetime
from os.path import join, realpath, dirname

from dt_shell import DTCommandAbs, dtslogger
from past.builtins import raw_input

from utils.cli_utils import start_command_in_subprocess
from utils.docker_utils import get_local_client, get_duckiebot_client, IMAGE_BASE, IMAGE_CALIBRATION


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        script_file = join(dirname(realpath(__file__)), 'calibrate_duckiebot.sh')

        prog = 'dts duckiebot calibrate_extrinsics DUCKIEBOT_NAME'
        usage = """
Calibrate: 

    %(prog)s
"""

        parser = argparse.ArgumentParser(prog=prog, usage=usage)
        parser.add_argument('hostname', default=None, help='Name of the Duckiebot to calibrate')
        parsed_args = parser.parse_args(args)

        from utils.networking_utils import get_duckiebot_ip

        duckiebot_ip = get_duckiebot_ip(parsed_args.hostname)
        # shell.calibrate(duckiebot_name=args[0], duckiebot_ip=duckiebot_ip)
        script_cmd = '/bin/bash %s %s %s' % (script_file, parsed_args.hostname, duckiebot_ip)

        start_command_in_subprocess(script_cmd)


def calibrate(duckiebot_name, duckiebot_ip):
    local_client = get_local_client()
    duckiebot_client = get_duckiebot_client(duckiebot_ip)

    duckiebot_client.images.pull(IMAGE_BASE)
    local_client.images.pull(IMAGE_CALIBRATION)

    duckiebot_client.containers.get('ros-picam').stop()

    timestamp = datetime.date.today().strftime('%Y%m%d%H%M%S')

    print("{}\nPlace the Duckiebot on the calibration patterns and press ENTER.".format('*' * 20))

    log_file = 'out-calibrate-extrinsics-%s-%s' % (duckiebot_name, timestamp)
    source_env = 'source /home/software/docker/env.sh'
    rosrun_params = '-o /data/{0} > /data/{0}.log'.format(log_file)
    ros_pkg = 'complete_image_pipeline calibrate_extrinsics'
    start_command = '{0} && rosrun {1} {2}'.format(source_env, ros_pkg, rosrun_params)
    dtslogger.info('Running command: {}'.format(start_command))

    duckiebot_client.containers.run(image=IMAGE_CALIBRATION,
                                    privileged=True,
                                    network_mode='host',
                                    datavol={'/data': {'bind': '/data'}},
                                    command="/bin/bash -c '%s'" % start_command)

    raw_input("{}\nPlace the Duckiebot in a lane and press ENTER.".format('*' * 20))

    log_file = 'out-pipeline-%s-%s' % (duckiebot_name, timestamp)
    rosrun_params = '-o /data/{0} > /data/{0}.log'.format(log_file)
    ros_pkg = 'complete_image_pipeline single_image_pipeline'
    start_command = '{0} && rosrun {1} {2}'.format(source_env, ros_pkg, rosrun_params)
    dtslogger.info('Running command: {}'.format(start_command))

    duckiebot_client.containers.run(image=IMAGE_CALIBRATION,
                                    privileged=True,
                                    network_mode='host',
                                    datavol={'/data': {'bind': '/data'}},
                                    command="/bin/bash -c '%s'" % start_command)
