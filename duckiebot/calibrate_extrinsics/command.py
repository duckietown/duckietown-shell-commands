import argparse
import datetime

from dt_shell import DTCommandAbs, dtslogger
from past.builtins import raw_input
from utils.networking_utils import get_duckiebot_ip
from utils.docker_utils import get_remote_client, bind_duckiebot_data_dir, default_env, remove_if_running


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):

        prog = 'dts duckiebot calibrate_extrinsics DUCKIEBOT_NAME'
        usage = """
Calibrate: 

    %(prog)s
"""

        parser = argparse.ArgumentParser(prog=prog, usage=usage)
        parser.add_argument('hostname', default=None, help='Name of the Duckiebot to calibrate')
        parser.add_argument('--base_image', dest='image',
                            default="duckietown/rpi-duckiebot-base:master19")
        parser.add_argument('--no_verification', action='store_true', default=False,
                            help="If you don't have a lane you can skip the verificaiton step")

        parsed_args = parser.parse_args(args)
        hostname = parsed_args.hostname
        duckiebot_ip = get_duckiebot_ip(hostname)
        duckiebot_client = get_remote_client(duckiebot_ip)

        calibration_container_name = "extrinsic_calibration"
        validation_container_name = "extrinsic_calibration_validation"
        remove_if_running(duckiebot_client,calibration_container_name)
        remove_if_running(duckiebot_client,validation_container_name)

        # need to temporarily pause the image streaming from the robot
        try:
            duckiebot_containers = duckiebot_client.containers.list()
            interface_container_found = False
            for c in duckiebot_containers:
                if 'duckiebot-interface' in c.name:
                    interface_container_found = True
                    interface_container = c
                    dtslogger.info("Temporarily stopping image streaming...")
                    interface_container.stop()
        except Exception as e:
            dtslogger.warn(
                "Not sure if the duckiebot-interface is running because we got and exception when trying: %s" % e)

        image = parsed_args.image

        timestamp = datetime.date.today().strftime('%Y%m%d%H%M%S')

        raw_input("{}\nPlace the Duckiebot on the calibration patterns and press ENTER.".format('*' * 20))
        log_file = 'out-calibrate-extrinsics-%s-%s' % (hostname, timestamp)
        rosrun_params = '-o /data/{0} > /data/{0}.log'.format(log_file)
        ros_pkg = 'complete_image_pipeline calibrate_extrinsics'
        start_command = 'rosrun {0} {1}'.format(ros_pkg, rosrun_params)
        dtslogger.info('Running command: {}'.format(start_command))

        env = default_env(hostname,duckiebot_ip)

        duckiebot_client.containers.run(image=image,
                                    name=calibration_container_name,
                                    privileged=True,
                                    network_mode='host',
                                    volumes=bind_duckiebot_data_dir(),
                                    command="/bin/bash -c '%s'" % start_command,
                                    environment=env)

        if not parsed_args.no_verification:
            raw_input("{}\nPlace the Duckiebot in a lane and press ENTER.".format('*' * 20))
            log_file = 'out-pipeline-%s-%s' % (hostname, timestamp)
            rosrun_params = '-o /data/{0} > /data/{0}.log'.format(log_file)
            ros_pkg = 'complete_image_pipeline single_image_pipeline'
            start_command = 'rosrun {0} {1}'.format(ros_pkg, rosrun_params)
            dtslogger.info('Running command: {}'.format(start_command))

            duckiebot_client.containers.run(image=image,
                                    name=validation_container_name,
                                    privileged=True,
                                    network_mode='host',
                                    volumes=bind_duckiebot_data_dir(),
                                    command="/bin/bash -c '%s'" % start_command,
                                    environment=env
                                            )


        # restart the camera streaming
        try:
            all_duckiebot_containers = duckiebot_client.containers.list(all=True)
            found = False
            for c in all_duckiebot_containers:
                if 'duckiebot-interface' in c.name:
                    found = True
                    dtslogger.info("Restarting image streaming...")
                    c.start()
        except Exception as e:
            dtslogger.warn(
                "Not sure if the duckiebot-interface is running because we got and exception when trying: %s" % e)
