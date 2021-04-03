import argparse
import sys
from enum import IntEnum
from threading import Thread

import docker
import requests
from dt_shell import DTCommandAbs, dtslogger, DTShell

from utils.cli_utils import ask_confirmation
from utils.docker_utils import get_client, get_endpoint_architecture
from utils.duckietown_utils import get_distro_version
from utils.misc_utils import sanitize_hostname
from utils.robot_utils import log_event_on_robot

UPGRADE_IMAGE = "duckietown/dt-firmware-upgrade:{distro}-{arch}"
HEALTH_CONTAINER_NAME = "device-health"
DEBUG = 0


class ExitCode(IntEnum):
    # NOTE: Please, DO NOT change these values, they are agreed upon with the image
    NOTHING_TO_DO = 255
    SUCCESS = 1
    HARDWARE_NOT_FOUND = 2
    HARDWARE_BUSY = 3
    HARDWARE_WRONG_MODE = 4
    FIRMWARE_UP_TO_DATE = 5
    FIRMWARE_NEEDS_UPDATE = 6
    GENERIC_ERROR = 9


class DTCommand(DTCommandAbs):

    help = 'Upgrades a Duckiebot\'s battery firmware'

    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts duckiebot battery upgrade DUCKIEBOT_NAME"
        parser = argparse.ArgumentParser(prog=prog)
        parser.add_argument("--force", action='store_true', default=False, help="Force the update")
        parser.add_argument("--version", type=str, default=None, help="Force a specific version")
        parser.add_argument("--debug", action='store_true', default=False, help="Debug mode")
        parser.add_argument("duckiebot", default=None, help="Name of the Duckiebot")
        parsed = parser.parse_args(args)
        # want the use NOT TO interrupt this command
        dtslogger.warning("DO NOT unplug the battery, turn off your robot, or interrupt this "
                          "command. It might cause irreversible damage to the battery.")
        # check if the health-api container is running
        dtslogger.info("Releasing battery...")
        hostname = sanitize_hostname(parsed.duckiebot)
        client = get_client(hostname)
        device_health = None
        try:
            device_health = client.containers.get(HEALTH_CONTAINER_NAME)
        except docker.errors.NotFound:
            # this is fine
            pass
        except docker.errors.APIError as e:
            dtslogger.error(str(e))
            exit(1)
        # stop device health container
        if device_health is not None:
            device_health.reload()
            if device_health.status == "running":
                dtslogger.debug(f"Stopping '{HEALTH_CONTAINER_NAME}' container...")
                try:
                    device_health.stop()
                except docker.errors.APIError as e:
                    dtslogger.error(str(e))
                    exit(1)
                dtslogger.debug(f"Container '{HEALTH_CONTAINER_NAME}' stopped.")
            else:
                dtslogger.debug(f"Container '{HEALTH_CONTAINER_NAME}' not running.")
        else:
            dtslogger.debug(f"Container '{HEALTH_CONTAINER_NAME}' not found.")
        # the battery should be free now
        dtslogger.info("Battery released!")
        # compile upgrade image name
        arch = get_endpoint_architecture(hostname)
        distro = get_distro_version(shell)
        image = UPGRADE_IMAGE.format(distro=distro, arch=arch)
        dtslogger.info("Checking battery...")
        dtslogger.debug(f"Running image '{image}'")
        extra_env = {}

        # forcing a version means forcing an update (aka skipping the check)
        if parsed.version is not None:
            extra_env = {"FORCE_BATTERY_FW_VERSION": parsed.version}
            parsed.force = True

        # step 1. read the battery current version (unless forced)
        if not parsed.force:
            # we run the helper in "check" mode and expect one of:
            #   - FIRMWARE_UP_TO_DATE           user will be notified
            #   - FIRMWARE_NEEDS_UPDATE         all well, user will be asked to confirm
            while True:
                exit_code = None
                logs = None
                try:
                    check = client.containers.run(
                        image=image,
                        name="dts-battery-firmware-upgrade-check",
                        privileged=True,
                        detach=True,
                        environment={
                            "DEBUG": DEBUG
                        },
                        command=["--", "--battery", "--check"]
                    )
                    try:
                        data = check.wait(timeout=10)
                        exit_code, logs = data['StatusCode'], check.logs().decode('utf-8')
                    except requests.exceptions.ReadTimeout:
                        check.stop()
                    finally:
                        check.remove()
                    if logs:
                        print(logs)
                except docker.errors.APIError as e:
                    dtslogger.error(str(e))
                    exit(1)
                # make sure we know what happened
                status = None
                # noinspection PyBroadException
                try:
                    status = ExitCode(exit_code)
                except BaseException:
                    dtslogger.error(f"Unrecognized status code: {exit_code}.\n"
                                    f"Contact your administrator.")
                    exit(1)
                # ---
                # FIRMWARE_UP_TO_DATE
                if status == ExitCode.FIRMWARE_UP_TO_DATE:
                    dtslogger.info(f"The battery on {parsed.duckiebot} does not need to be"
                                   f" updated. Enjoy the rest of your day.")
                    # re-activate device-health
                    if device_health:
                        dtslogger.info("Re-engaging battery...")
                        device_health.start()
                        dtslogger.info("Battery returned to work!")
                    exit(0)
                #
                elif status == ExitCode.FIRMWARE_NEEDS_UPDATE:
                    granted = ask_confirmation("An updated firmware is available",
                                               question="Do you want to update the battery now?")
                    if not granted:
                        dtslogger.info("Enjoy the rest of your day.")
                        exit(0)
                    break
                # any other status
                else:
                    answer = input("Press ENTER to retry, 'q' to quit... ")
                    if answer.strip() == 'q':
                        exit(0)
                    continue

        # step 2: make sure everything is ready for update
        dtslogger.info("Switch your battery to \"Boot Mode\" by double pressing the button on the "
                       "battery.")
        # we run the helper in "dryrun" mode and expect:
        #   - SUCCESS           all well, next is update
        txt = 'when done'
        while True:
            answer = input(f"Press ENTER {txt}, 'q' to quit... ")
            if answer.strip() == 'q':
                exit(0)
            try:
                client.containers.run(
                    image=image,
                    name="dts-battery-firmware-upgrade-dryrun",
                    auto_remove=True,
                    privileged=True,
                    environment={
                        "DEBUG": DEBUG,
                        **extra_env
                    },
                    command=["--", "--battery", "--dry-run"]
                )
            except docker.errors.APIError as e:
                dtslogger.error(str(e))
                exit(1)
            except docker.errors.ContainerError as e:
                exit_code = e.exit_status
                # make sure we know what happened
                status = None
                # noinspection PyBroadException
                try:
                    status = ExitCode(exit_code)
                except BaseException:
                    dtslogger.error(f"Unrecognized status code: {exit_code}.\n"
                                    f"Contact your administrator.")
                    exit(1)
                # SUCCESS
                if status == ExitCode.SUCCESS:
                    break
                # HARDWARE_WRONG_MODE
                elif status == ExitCode.HARDWARE_WRONG_MODE:
                    # battery found but not in boot mode
                    dtslogger.error("Battery detected in 'Normal Mode', but it needs to be in "
                                    "'Boot Mode'. You can switch mode by pressing the button "
                                    "on the battery twice.")
                    txt = 'to retry'
                    continue
                # HARDWARE_BUSY
                elif status == ExitCode.HARDWARE_BUSY:
                    # battery is busy
                    dtslogger.error("Battery detected but another process is using it. "
                                    "This should not have happened. Contact your administrator.")
                    exit(1)
                # any other status
                else:
                    dtslogger.error(f"The battery reported the status '{status.name}'")
                    exit(1)

        # step 3: perform update
        # it looks like the update is going to happen, mark the event
        log_event_on_robot(hostname, 'battery/upgrade')
        dtslogger.info("Updating battery...")
        # we run the helper in "normal" mode and expect:
        #   - SUCCESS           all well, battery updated successfully
        exit_code = None
        try:
            container = client.containers.run(
                image=image,
                name="dts-battery-firmware-upgrade-do",
                auto_remove=True,
                privileged=True,
                detach=True,
                environment={
                    "DEBUG": DEBUG,
                    **extra_env
                },
                command=["--", "--battery"]
            )
            DTCommand._consume_output(container.attach(stream=True))
            data = container.wait(condition="removed")
            exit_code = data['StatusCode']
        except docker.errors.APIError as e:
            dtslogger.error(str(e))
            exit(1)

        # make sure we know what happened
        status = None
        # noinspection PyBroadException
        try:
            status = ExitCode(exit_code)
        except BaseException:
            dtslogger.error(f"Unrecognized status code: {exit_code}.\n"
                            f"Contact your administrator.")
            exit(1)
        # SUCCESS
        if status == ExitCode.SUCCESS:
            dtslogger.info(f"Battery on '{parsed.duckiebot}' successfully updated!")
        # any other status
        else:
            dtslogger.error(f"The battery reported the status '{status.name}'")
            exit(1)

        # re-activate device-health
        if device_health:
            dtslogger.info("Re-engaging battery...")
            device_health.start()
            dtslogger.info("Battery returned to work happier than ever!")

    @staticmethod
    def _consume_output(logs):
        def _printer():
            for line in logs:
                sys.stdout.write(line.decode('utf-8'))
        worker = Thread(target=_printer())
        worker.start()



