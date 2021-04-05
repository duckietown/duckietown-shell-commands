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
    get_endpoint_architecture,
)
from utils.duckietown_utils import get_distro_version
from utils.misc_utils import sanitize_hostname
from utils.networking_utils import get_duckiebot_ip


CALIBRATE_IMAGE = "duckietown/dt-core:{distro}-{arch}"


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):

        prog = "dts duckiebot calibrate_extrinsics DUCKIEBOT_NAME"
        usage = """
Calibrate:

    %(prog)s
"""

        parser = argparse.ArgumentParser(prog=prog, usage=usage)
        parser.add_argument("duckiebot", default=None, help="Name of the Duckiebot to calibrate")
        parser.add_argument(
            "--no_verification",
            action="store_true",
            default=False,
            help="If you don't have a lane you can skip the verification step",
        )
        parsed = parser.parse_args(args)
        # ---
        hostname = sanitize_hostname(parsed.duckiebot)
        duckiebot_ip = get_duckiebot_ip(parsed.duckiebot)
        duckiebot_client = get_remote_client(duckiebot_ip)

        calibration_container_name = "extrinsic_calibration"
        validation_container_name = "extrinsic_calibration_validation"
        remove_if_running(duckiebot_client, calibration_container_name)
        remove_if_running(duckiebot_client, validation_container_name)

        check_if_running(duckiebot_client, "duckiebot-interface")

        arch = get_endpoint_architecture(hostname)
        distro = get_distro_version(shell)
        image = CALIBRATE_IMAGE.format(distro=distro, arch=arch)
        dtslogger.info(f"Target architecture automatically set to {arch}.")

        raw_input(f"{'*' * 20}\nPlace the Duckiebot on the calibration patterns and press ENTER.")
        dtslogger.info("Running extrinsics calibration...")

        env = default_env(parsed.duckiebot, duckiebot_ip)

        pull_if_not_exist(duckiebot_client, image)

        duckiebot_client.containers.run(
            image=image,
            name=calibration_container_name,
            privileged=True,
            network_mode="host",
            volumes=bind_duckiebot_data_dir(),
            command="dt-launcher-calibrate-extrinsics",
            environment=env,
            remove=True,
        )
        dtslogger.info("Done!")

        if not parsed.no_verification:
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
                remove=True,
            )
            dtslogger.info("Done!")
