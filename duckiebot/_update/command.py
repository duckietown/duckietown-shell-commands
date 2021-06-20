import json
import os
import time
import math
import argparse
import functools
import random

import requests

import docker as dockerlib

from dt_shell import DTCommandAbs, dtslogger, DTShell
from utils.docker_utils import (
    pull_image,
    get_endpoint_architecture_from_ip,
    get_remote_client,
    get_client,
    get_endpoint_architecture,
    DEFAULT_DOCKER_TCP_PORT,
)
from utils.cli_utils import ProgressBar, ask_confirmation
from utils.duckietown_utils import get_distro_version
from utils.networking_utils import get_duckiebot_ip


class DTCommand(DTCommandAbs):

    CODE_API_CONTAINER_CONFIG = {
        "restart_policy": {"Name": "always"},
        "network_mode": "host",
        "volumes": [
            "/data:/data",
            "/code:/user_code",
            "/var/run/docker.sock:/var/run/docker.sock",
            "/var/run/avahi-daemon/socket:/var/run/avahi-daemon/socket",
        ],
    }

    CODE_API_PORT = 8086

    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts duckiebot update"
        parser = argparse.ArgumentParser(prog=prog)
        # define arguments
        parser.add_argument(
            "--full",
            default=False,
            action="store_true",
            help="Pull and recreate the code-api container as well.",
        )
        parser.add_argument(
            "--codeapi-pull",
            default=False,
            action="store_true",
            help="Pull new image for code-api container",
        )
        parser.add_argument(
            "--codeapi-recreate",
            default=False,
            action="store_true",
            help="Recreate the code-api container",
        )
        parser.add_argument(
            "--check",
            default=False,
            action="store_true",
            help="Force re-check",
        )
        parser.add_argument(
            "-y",
            "--yes",
            default=False,
            action="store_true",
            help="Don't ask for confirmation",
        )
        parser.add_argument(
            "--local",
            default=False,
            action="store_true",
            help="Run the updater module locally",
        )
        parser.add_argument("vehicle", nargs=1, help="Name of the Duckiebot to check software status for")
        # parse arguments
        parsed = parser.parse_args(args)
        vehicle = parsed.vehicle[0].rstrip(".local")
        hostname = f"{vehicle}.local"
        code_api_port = DTCommand.CODE_API_PORT

        # open Docker client
        if parsed.local:
            docker = get_client()
            endpoint_arch = get_endpoint_architecture()
            container_name = f"code-api-{vehicle}"
        else:
            duckiebot_ip = get_duckiebot_ip(vehicle)
            docker = get_remote_client(duckiebot_ip)
            endpoint_arch = get_endpoint_architecture_from_ip(duckiebot_ip)
            container_name = "code-api"

        # define code-api image name
        distro = get_distro_version(shell)
        code_api_image = f"duckietown/dt-code-api:{distro}-{endpoint_arch}"
        dtslogger.debug(f"Working with code-api image `{code_api_image}`")
        version_str = ""

        # full?
        if parsed.full:
            parsed.codeapi_pull = True
            parsed.codeapi_recreate = True
            if parsed.local:
                dtslogger.error("You cannot use the option `--full` together with `--local`.")
                DTCommand.cleanup(parsed)
                return

        # local?
        if parsed.local:
            parsed.check = True
            # get a random port within the range [10000, 20000
            code_api_port = random.randint(10000, 20000)

        if parsed.codeapi_pull:
            num_trials = 10
            # pull newest version of code-api container
            for trial_no in range(1, num_trials + 1, 1):
                try:
                    if trial_no == 1:
                        dtslogger.info("Pulling new image for module `dt-code-api`. Be patient...")
                    dtslogger.debug(f"Trial {trial_no}/{num_trials}: Pulling image `dt-code-api`.")
                    # ---
                    pull_image(code_api_image, endpoint=docker)
                    version_str = " new version of"
                    break
                except dockerlib.errors.APIError:
                    if trial_no == num_trials:
                        dtslogger.error(
                            "An error occurred while pulling the module dt-code-api. " "Aborting."
                        )
                        DTCommand.cleanup(parsed)
                        return
                    time.sleep(2)

        if parsed.codeapi_recreate or parsed.check:
            # get old code-api container
            container = None
            try:
                container = docker.containers.get(container_name)
            except dockerlib.errors.NotFound:
                # container not found, this is ok
                pass

            # get docker-compose labels
            compose_labels = {}
            if container is not None:
                compose_labels = {
                    key: value
                    for key, value in container.labels.items()
                    if key.startswith("com.docker.compose.")
                }

            # stop old code-api container
            if container is not None:
                try:
                    if container.status in ["running", "restarting", "paused"]:
                        dtslogger.info(f"Stopping container `{container_name}`.")
                        container.stop()
                except dockerlib.errors.APIError:
                    dtslogger.error(
                        f"An error occurred while stopping the {container_name} " f"container. Aborting."
                    )
                    DTCommand.cleanup(parsed)
                    return

            # remove old code-api container
            if container is not None:
                try:
                    dtslogger.info(f"Removing container `{container_name}`.")
                    container.remove()
                except dockerlib.errors.APIError:
                    dtslogger.error("An error occurred while removing the code-api container. " "Aborting.")
                    DTCommand.cleanup(parsed)
                    return

            # run new code-api container
            container_cfg = {
                **DTCommand.CODE_API_CONTAINER_CONFIG,
                **(
                    {
                        "environment": {"TARGET_ENDPOINT": f"{hostname}:{DEFAULT_DOCKER_TCP_PORT}"},
                        "volumes": {
                            os.path.expanduser("~/.docker/"): {"bind": "/root/.docker/", "mode": "rw"},
                            "/var/run/avahi-daemon/socket": {
                                "bind": "/var/run/avahi-daemon/socket",
                                "mode": "rw",
                            },
                        },
                        "ports": {f"{DTCommand.CODE_API_PORT}/tcp": ("127.0.0.1", code_api_port)},
                    }
                    if parsed.local
                    else {}
                ),
            }
            if parsed.local:
                del container_cfg["restart_policy"]
                del container_cfg["network_mode"]

            try:
                dtslogger.info(f"Running{version_str} `dt-code-api` module.")
                docker.containers.run(
                    code_api_image, labels=compose_labels, detach=True, name=container_name, **container_cfg
                )
            except dockerlib.errors.ImageNotFound:
                # this should not have happened
                dtslogger.info("Image for module `dt-code-api` not found. Contact administrator.")
                DTCommand.cleanup(parsed)
                return
            except dockerlib.errors.APIError as e:
                # this should not have happened
                dtslogger.info(
                    f"An error occurred while running the {container_name} container. "
                    f"The error reads:\n\n{str(e)}"
                )
                DTCommand.cleanup(parsed)
                return

        # wait for the code-api to boot up
        stime = time.time()
        checkpoint = 0
        max_checkpoints = 12
        checkpoint_every_sec = 10
        first_contact_time = None
        code_status = {}
        code_api_url = functools.partial(DTCommand.get_code_api_url, parsed, code_api_port)
        dtslogger.info("Waiting for the dt-code-api module...")
        while True:
            try:
                url = code_api_url("modules/status")
                dtslogger.debug(f'GET: "{url}"')
                res = requests.get(url, timeout=5)
                if first_contact_time is None:
                    first_contact_time = time.time()
                code_status = res.json()["data"]
                # ---
                need_to_wait_more = False
                # make sure we are monitoring something
                if len(code_status) == 0:
                    need_to_wait_more = True
                # check status of every module, make sure they are all checked out
                for _, module in code_status.items():
                    if module["status"] in ["UNKNOWN"]:
                        need_to_wait_more = True
                # wait a little longer if necessary
                if not need_to_wait_more:
                    break
            except requests.exceptions.RequestException:
                pass
            except BaseException:
                pass
            new_checkpoint = int(math.floor((time.time() - stime) / checkpoint_every_sec))
            if new_checkpoint > checkpoint:
                dtslogger.info("Still waiting...")
                checkpoint = new_checkpoint
            if checkpoint > max_checkpoints:
                dtslogger.error(
                    "The dt-code-api module took too long to boot up, "
                    "something must be wrong. Contact administrator."
                )
                DTCommand.cleanup(parsed)
                return
            time.sleep(2)
        dtslogger.debug("Status:\n\n" + json.dumps(code_status, sort_keys=True, indent=4))

        # ask the user for confirmation
        modules = {}
        for status in ["UPDATED", "BEHIND", "AHEAD", "NOT_FOUND", "UPDATING", "ERROR"]:
            modules[status] = {k: m for k, m in code_status.items() if m["status"] == status}

        # talk to the user
        print(
            f"\n"
            f"Status:\n"
            f"\t- Modules to update ({len(modules['BEHIND'])}):"
            + f"\n\t\t-".join([""] + list(modules["BEHIND"].keys()))
            + f"\n"
            f"\t- Modules up-to-date ({len(modules['UPDATED'])}):"
            + f"\n\t\t-".join([""] + list(modules["UPDATED"].keys()))
            + f"\n"
            f"\t- Modules with errors ({len(modules['ERROR'])}):"
            + f"\n\t\t-".join([""] + list(modules["ERROR"].keys()))
            + f"\n"
            f"\t- Modules not found ({len(modules['NOT_FOUND'])}):"
            + f"\n\t\t-".join([""] + list(modules["NOT_FOUND"].keys()))
            + f"\n"
            f"\t- Modules ahead of the remote counterpart ({len(modules['AHEAD'])}):"
            + f"\n\t\t-".join([""] + list(modules["AHEAD"].keys()))
            + f"\n"
        )
        if len(modules["BEHIND"]) == 0:
            dtslogger.info("Nothing to do.")
            DTCommand.cleanup(parsed)
            return

        # there is something to update
        granted = parsed.yes or ask_confirmation(
            f"{len(modules['BEHIND'])} modules will be updated",
            question="Do you want to continue?",
            default="n",
        )

        if not granted:
            dtslogger.info("Sure, I won't update then.")
            DTCommand.cleanup(parsed)
            return

        # start update
        try:
            for module in modules["BEHIND"]:
                try:
                    dtslogger.info(f"Updating module `{module}`...")
                    update_url = DTCommand.get_code_api_url(parsed, code_api_port, f"module/update/{module}")
                    try:
                        dtslogger.debug(f'GET: "{update_url}"')
                        res = requests.get(update_url, timeout=5)
                        data = res.json()
                        if data["status"] == "error":
                            dtslogger.warning(data["message"])
                            dtslogger.warning(f"Skipping update for module `{module}`.")
                            continue
                        if data["status"] != "ok":
                            dtslogger.warning(f"Error occurred while updating module `{module}`.")
                            dtslogger.warning(f"Skipping update for module `{module}`.")
                            continue
                    except requests.exceptions.RequestException:
                        pass
                    # allow some time for the code-api to pick up the action
                    time.sleep(2)
                    # start monitoring update
                    res = DTCommand.monitor_update(parsed, code_api_port, module)
                    if not res:
                        raise requests.exceptions.RequestException()
                    dtslogger.info(f"Module `{module}` successfully updated!")
                except requests.exceptions.RequestException:
                    dtslogger.error(f"An error occurred while updating the module `{module}`.")
                    continue
                finally:
                    print()
        except KeyboardInterrupt:
            dtslogger.info("Aborted")
            DTCommand.cleanup(parsed)
            return
        print()
        DTCommand.cleanup(parsed)

    @staticmethod
    def cleanup(parsed):
        if parsed.local:
            dtslogger.info("Cleaning up...")
            vehicle = parsed.vehicle[0].rstrip(".local")
            client = get_client()
            container_name = f"code-api-{vehicle}"
            try:
                container = client.containers.get(container_name)
                container.stop()
                container.remove()
            except BaseException:
                dtslogger.warning(
                    "We had issues cleaning up the containers before exiting. "
                    "Be aware there might be some leftover somewhere. Sorry!"
                )

    @staticmethod
    def get_code_api_url(parsed, port, resource):
        if parsed.local:
            return f"http://localhost:{port}/{resource}"
        else:
            vehicle = parsed.vehicle[0].rstrip(".local")
            hostname = f"{vehicle}.local"
            return f"http://{hostname}/code/{resource}"

    @staticmethod
    def monitor_update(parsed, port, module):
        url = DTCommand.get_code_api_url(parsed, port, f"modules/status")
        dtslogger.debug(f'GET(loop): "{url}"')
        pbar = ProgressBar()
        while True:
            try:
                res = requests.get(url, timeout=5)
                code_status = res.json()["data"]
                if module not in code_status:
                    dtslogger.error(f"Module `{module}` not found. Skipping.")
                    return False
                if code_status[module]["status"] == "UPDATED":
                    pbar.done()
                    return True
                if code_status[module]["status"] != "UPDATING" or "progress" not in code_status[module]:
                    time.sleep(1)
                    continue
                pbar.set_header(code_status[module]["status_txt"] or "Updating")
                pbar.update(code_status[module]["progress"])
            except requests.exceptions.RequestException:
                pass
            time.sleep(1)
        pbar.done()
        return False
