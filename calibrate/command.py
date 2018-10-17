from __future__ import print_function

import argparse
import datetime
import os
import platform
import subprocess
import sys
from os.path import join, realpath, dirname, expanduser
from subprocess import call

from dt_shell import DTCommandAbs, dtslogger
from utils.networking import get_duckiebot_ip


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        script_file = join(dirname(realpath(__file__)), 'calibrate_duckiebot.sh')

        prog = 'dts calibrate DUCKIEBOT_NAME'
        usage = """
Calibrate: 

    %(prog)s
"""

        parser = argparse.ArgumentParser(prog=prog, usage=usage)
        parser.add_argument('hostname', default=None, help='Name of the Duckiebot to calibrate')
        args = parser.parse_args()

        duckiebot_ip = get_duckiebot_ip(args[0])
        # shell.calibrate(duckiebot_name=args[0], duckiebot_ip=duckiebot_ip)
        script_cmd = '/bin/bash %s %s %s' % (script_file, args.hostname, duckiebot_ip)

        env = {}
        env.update(os.environ)
        V = 'DOCKER_HOST'
        if V in env:
            msg = 'I will ignore %s because the calibrate command knows what it\'s doing.' % V
            dtslogger.info(msg)
            env.pop(V)

        ret = call(script_cmd, shell=True, stdin=sys.stdin, stderr=sys.stderr, stdout=sys.stdout, env=env)

        if ret == 0:
            print('Done!')
        else:
            msg = ('An error occurred while running the calibration procedure, please check and try again (%s).' % ret)
            raise Exception(msg)

    def calibrate(self, duckiebot_name, duckiebot_ip):
        import docker
        local_client = docker.from_env()
        duckiebot_client = docker.DockerClient('tcp://' + duckiebot_ip + ':2375')
        operating_system = platform.system()

        IMAGE_CALIBRATION = 'duckietown/rpi-duckiebot-calibration:master18'
        IMAGE_BASE = 'duckietown/rpi-duckiebot-base:master18'

        duckiebot_client.images.pull(IMAGE_BASE)
        local_client.images.pull(IMAGE_CALIBRATION)
        user_home = expanduser("~")
        datavol = {'%s/data' % user_home: {'bind': '/data'}}

        env_vars = {
            'ROS_MASTER': duckiebot_name,
            'DUCKIEBOT_NAME': duckiebot_name,
            'DUCKIEBOT_IP': duckiebot_ip,
            'QT_X11_NO_MITSHM': True
        }

        if operating_system == 'Linux':
            call(["xhost", "+"])
            local_client.containers.run(image=IMAGE_CALIBRATION,
                                        network_mode='host',
                                        volumes=datavol,
                                        privileged=True,
                                        env_vars=env_vars)
        if operating_system == 'Darwin':
            IP = subprocess.check_output(['/bin/sh', '-c', 'ifconfig en0 | grep inet | awk \'$1=="inet" {print $2}\''])
            env_vars['IP'] = IP
            call(["xhost", "+IP"])
            local_client.containers.run(image=IMAGE_CALIBRATION,
                                        network_mode='host',
                                        volumes=datavol,
                                        privileged=True,
                                        env_vars=env_vars)

        duckiebot_client.containers.get('ros-picam').stop()

        timestamp = datetime.date.today().strftime('%Y%m%d%H%M%S')
        name = 'out-calibrate-extrinsics-%s-%s' % (duckiebot_name, timestamp)
        sname = 'out-simulation-%s-%s' % (duckiebot_name, timestamp)
        vname = 'out-pipeline-%s-%s' % (duckiebot_name, timestamp)

        print("********************")
        raw_input("Place the Duckiebot on the calibration patterns and press ENTER.")

        duckiebot_client.containers.run(image=IMAGE_CALIBRATION,
                                        privileged=True,
                                        network_mode='host',
                                        datavol={'/data': {'bind': '/data'}},
                                        command='/bin/bash',
                                        kwargs=['-c', 'source /home/software/docker/env.sh && rosrun complete_image_pipeline calibrate_extrinsics -o /data/%s > /data/%s.log' % (name, name)]
                                        )

        print("********************")
        raw_input("Place the Duckiebot in a lane and press ENTER.")

        duckiebot_client.containers.run(image=IMAGE_CALIBRATION,
                                        privileged=True,
                                        network_mode='host',
                                        datavol={'/data': {'bind': '/data'}},
                                        command='/bin/bash',
                                        kwargs=['-c','source /home/software/docker/env.sh && rosrun complete_image_pipeline single_image_pipeline -o /data/%s> /data/%s.log'%(vname, vname)]
                                        )

        print("********************")
        print("To perform the wheel calibration, follow the steps described in the Duckiebook.")
        print("http://docs.duckietown.org/DT18/opmanual_duckiebot/out/wheel_calibration.html")
        raw_input("You will now be given a container running on the Duckiebot for wheel calibration.")


        duckiebot_client.containers.run(image=IMAGE_CALIBRATION,
                                        privileged=True,
                                        network_mode='host',
                                        datavol={'/data': {'bind': '/data'}},
                                        command='/bin/bash')
