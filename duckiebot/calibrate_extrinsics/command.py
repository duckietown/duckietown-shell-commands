import argparse
import datetime

from past.builtins import raw_input

from dt_shell import DTCommandAbs, DTShell, dtslogger
from utils.docker_utils import (
    bind_duckiebot_data_dir,
    default_env,
    get_remote_client,
    remove_if_running,
    pull_if_not_exist,
    check_if_running,
)
from utils.networking_utils import get_duckiebot_ip


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):

        prog = "dts duckiebot calibrate_extrinsics DUCKIEBOT_NAME"
        usage = """
Calibrate: 

    %(prog)s
"""

        parser = argparse.ArgumentParser(prog=prog, usage=usage)
        parser.add_argument(
            "hostname", default=None, help="Name of the Duckiebot to calibrate"
        )
        parser.add_argument(
            "--base_image",
            dest="image",
            default="duckietown/dt-core:daffy-arm32v7",
        )
        parser.add_argument(
            "--no_verification",
            action="store_true",
            default=True,
            help="If you don't have a lane you can skip the verification step",
        )

        parsed_args = parser.parse_args(args)
        hostname = parsed_args.hostname
        duckiebot_ip = get_duckiebot_ip(hostname)
        duckiebot_client = get_remote_client(duckiebot_ip)

        calibration_container_name = "extrinsic_calibration"
        validation_container_name = "extrinsic_calibration_validation"
        remove_if_running(duckiebot_client, calibration_container_name)
        remove_if_running(duckiebot_client, validation_container_name)

        check_if_running(duckiebot_client, "duckiebot-interface")

        image = parsed_args.image

        timestamp = datetime.date.today().strftime("%Y%m%d%H%M%S")

        raw_input(
            "{}\nPlace the Duckiebot on the calibration patterns and press ENTER.".format(
                "*" * 20
            )
        )
        log_file = "out-calibrate-extrinsics-%s-%s" % (hostname, timestamp)
        rosrun_params = "-o /data/{0} > /data/{0}.log".format(log_file)
        ros_pkg = "complete_image_pipeline calibrate_extrinsics"
        start_command = "rosrun {0} {1}".format(ros_pkg, rosrun_params)
        dtslogger.info("Running command: {}".format(start_command))

        env = default_env(hostname, duckiebot_ip)

        pull_if_not_exist(duckiebot_client, image)

        duckiebot_client.containers.run(
            image=image,
            name=calibration_container_name,
            privileged=True,
            network_mode="host",
            volumes=bind_duckiebot_data_dir(),
            command="/bin/bash -c '%s'" % start_command,
            environment=env,
        )

        if not parsed_args.no_verification:
            raw_input(
                "{}\nPlace the Duckiebot in a lane and press ENTER.".format("*" * 20)
            )
            log_file = "out-pipeline-%s-%s" % (hostname, timestamp)
            rosrun_params = "-o /data/{0} > /data/{0}.log".format(log_file)
            ros_pkg = "complete_image_pipeline single_image_pipeline"
            start_command = "rosrun {0} {1}".format(ros_pkg, rosrun_params)
            dtslogger.info("Running command: {}".format(start_command))

            pull_if_not_exist(duckiebot_client, image)

            duckiebot_client.containers.run(
                image=image,
                name=validation_container_name,
                privileged=True,
                network_mode="host",
                volumes=bind_duckiebot_data_dir(),
                command="/bin/bash -c '%s'" % start_command,
                environment=env,
            )
