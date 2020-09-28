import argparse

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
            "hostname",
            default=None,
            help="Name of the Duckiebot to calibrate"
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

        raw_input(f"{'*' * 20}\nPlace the Duckiebot on the calibration patterns and press ENTER.")
        dtslogger.info("Running extrinsics calibration...")

        env = default_env(hostname, duckiebot_ip)

        pull_if_not_exist(duckiebot_client, image)

        duckiebot_client.containers.run(
            image=image,
            name=calibration_container_name,
            privileged=True,
            network_mode="host",
            volumes=bind_duckiebot_data_dir(),
            command="dt-launcher-calibrate-extrinsics",
            environment=env,
        )
        dtslogger.info("Done!")

        if not parsed_args.no_verification:
            raw_input(f"{'*' * 20}\nPlace the Duckiebot in a lane and press ENTER.")
            dtslogger.info("Running extrinsics calibration validation...")

            duckiebot_client.containers.run(
                image=image,
                name=validation_container_name,
                privileged=True,
                network_mode="host",
                volumes=bind_duckiebot_data_dir(),
                command="dt-launcher-validate-extrinsics",
                environment=env,
            )
            dtslogger.info("Done!")
