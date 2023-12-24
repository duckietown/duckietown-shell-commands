import argparse

from docker.errors import APIError, ImageNotFound

from dt_shell import DTCommandAbs, DTShell, dtslogger
from utils.cli_utils import start_command_in_subprocess
from utils.docker_utils import get_client, get_endpoint_architecture, pull_image
from utils.duckietown_utils import get_distro_version
from utils.misc_utils import sanitize_hostname
from utils.robot_utils import log_event_on_robot


UPGRADE_IMAGE = "duckietown/dt-firmware-upgrade:{distro}-{arch}"
UPGRADE_LAUNCHER = "dt-launcher-flash-hut"
DOCKER_CONTAINER_NAME = "dts-hut-firmware-upgrade"
DEBUG = 0


class DTCommand(DTCommandAbs):
    help = "Upgrades a Duckiebot's HUT firmware"

    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts duckiebot hut_upgrade"

        # parse cmd-line options
        parser = argparse.ArgumentParser(prog=prog)
        parser.add_argument("--image", default=None, help="Specific docker image to use (skip pulling)")
        parser.add_argument("duckiebot", default=None, help="Name of the Duckiebot")
        parsed = parser.parse_args(args)

        # retrieve robot hostname and the docker endpoint
        hostname = sanitize_hostname(parsed.duckiebot)
        client = get_client(hostname)

        # pull default image, or use specifed local image
        if parsed.image is None:
            # default image to use
            arch = get_endpoint_architecture(hostname)
            distro = get_distro_version(shell)
            image = UPGRADE_IMAGE.format(distro=distro, arch=arch)

            dtslogger.info(f'Pulling image "{image}" on [{hostname}]')
            # Try pulling the latest dt-firmware-upgrade image
            try:
                pull_image(image, endpoint=client)
            except KeyboardInterrupt:
                dtslogger.info("Aborting.")
                return
            except Exception as e:
                dtslogger.error(f'An error occurred while pulling the image "{image}": {str(e)}')
                exit(1)
            dtslogger.info(f'The image "{image}" is now up-to-date.')
        else:
            # use specified image
            image = parsed.image
            # ensure it is available
            try:
                _ = client.images.get(image)
            except ImageNotFound:
                dtslogger.error(f'The specified image is not present on host [{hostname}]: "{image}"')
                exit(1)
            except APIError as e:
                dtslogger.error(str(e))
                exit(1)
            dtslogger.info(f'Using the existing image of "{image}" on [{hostname}]')

        # log hut upgrade event
        log_event_on_robot(hostname, "hut/upgrade")

        # perform upgrade
        dtslogger.info("Updating HUT...")
        try:
            _ = client.containers.run(
                image=image,
                name=DOCKER_CONTAINER_NAME,
                command=UPGRADE_LAUNCHER,
                privileged=True,
                auto_remove=True,
                environment={"DEBUG": DEBUG},
                detach=True,
                # interactive
                stdin_open=True,
                tty=True,
                # mount data folder for recognizing robot computer type
                volumes=["/data:/data"],
            )
            # attach to the interactive container
            attach_cmd = f"docker -H {hostname} attach {DOCKER_CONTAINER_NAME}"
            start_command_in_subprocess(attach_cmd)

            dtslogger.info("Upgrade finished successfully. Please reboot your Duckiebot now.")
        except APIError as e:
            dtslogger.error(f"Docker client error: {str(e)}")
            exit(1)
        except Exception as e:
            # other errors and by user cancellation
            dtslogger.error("Unable to finish the upgrade.")
            exit(1)
