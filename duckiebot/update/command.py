import json
import time
import math
import argparse
import functools
import requests

import docker as dockerlib

from dt_shell import DTCommandAbs, dtslogger, DTShell
from utils.docker_utils import pull_image, get_endpoint_architecture_from_ip, get_remote_client
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
            "/var/run/avahi-daemon/socket:/var/run/avahi-daemon/socket"
        ]
    }

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
            "vehicle",
            nargs=1,
            help="Name of the Duckiebot to check software status for"
        )
        # parse arguments
        parsed = parser.parse_args(args)
        vehicle = parsed.vehicle[0].rstrip('.local')
        hostname = f"{vehicle}.local"

        # open Docker client
        duckiebot_ip = get_duckiebot_ip(vehicle)
        docker = get_remote_client(duckiebot_ip)

        # define code-api image name
        distro = get_distro_version(shell)
        endpoint_arch = get_endpoint_architecture_from_ip(duckiebot_ip)
        code_api_image = f"duckietown/dt-code-api:{distro}-{endpoint_arch}"
        dtslogger.debug(f"Working with code-api image `{code_api_image}`")

        # full?
        if parsed.full:
            parsed.codeapi_pull = True
            parsed.codeapi_recreate = True

        if parsed.codeapi_pull:
            num_trials = 10
            # pull newest version of code-api container
            for trial_no in range(1, num_trials + 1, 1):
                try:
                    if trial_no == 1:
                        dtslogger.info('Pulling new image for module `dt-code-api`. Be patient...')
                    dtslogger.debug(f'Trial {trial_no}/{num_trials}: Pulling image `dt-code-api`.')
                    # ---
                    pull_image(code_api_image, endpoint=docker)
                    break
                except dockerlib.errors.APIError:
                    if trial_no == num_trials:
                        dtslogger.error("An error occurred while pulling the module dt-code-api. "
                                        "Aborting.")
                        return
                    time.sleep(2)

        if parsed.codeapi_recreate or parsed.check:
            # get old code-api container
            container = None
            try:
                container = docker.containers.get('code-api')
            except dockerlib.errors.NotFound:
                # container not found, this is ok
                pass

            # get docker-compose labels
            compose_labels = {}
            if container is not None:
                compose_labels = {
                    key: value for key, value in container.labels.items()
                    if key.startswith("com.docker.compose.")
                }

            # stop old code-api container
            if container is not None:
                try:
                    if container.status in ['running', 'restarting', 'paused']:
                        dtslogger.info('Stopping container `code-api`.')
                        container.stop()
                except dockerlib.errors.APIError:
                    dtslogger.error("An error occurred while stopping the code-api container. "
                                    "Aborting.")
                    return

            # remove old code-api container
            if container is not None:
                try:
                    dtslogger.info('Removing container `code-api`.')
                    container.remove()
                except dockerlib.errors.APIError:
                    dtslogger.error("An error occurred while removing the code-api container. "
                                    "Aborting.")
                    return

            # run new code-api container
            try:
                dtslogger.info("Running new version of `dt-code-api` module.")
                docker.containers.run(
                    code_api_image,
                    labels=compose_labels,
                    detach=True,
                    name="code-api",
                    **DTCommand.CODE_API_CONTAINER_CONFIG
                )
            except dockerlib.errors.ImageNotFound:
                # this should not have happened
                dtslogger.info("Image for module `dt-code-api` not found. Contact administrator.")
                return
            except dockerlib.errors.APIError as e:
                # this should not have happened
                dtslogger.info("An error occurred while running the code-api container. "
                               f"The error reads:\n\n{str(e)}")
                return

        # wait for the code-api to boot up
        stime = time.time()
        checkpoint = 0
        max_checkpoints = 12
        checkpoint_every_sec = 10
        first_contact_time = None
        code_status = {}
        code_api_url = functools.partial(DTCommand.get_code_api_url, hostname)
        dtslogger.info("Waiting for the code-api module...")
        while True:
            try:
                url = code_api_url("modules/status")
                dtslogger.debug(f'GET: "{url}"')
                res = requests.get(url, timeout=5)
                if first_contact_time is None:
                    first_contact_time = time.time()
                code_status = res.json()['data']
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
                dtslogger.error("The code-api container took too long to boot up, "
                                "something must be wrong. Contact administrator.")
                return
            time.sleep(2)
        dtslogger.debug("Status:\n\n" + json.dumps(code_status, sort_keys=True, indent=4))

        # ask the user for confirmation
        modules = {}
        for status in ["UPDATED", "BEHIND", "AHEAD", "NOT_FOUND", "UPDATING", "ERROR"]:
            modules[status] = {
                k: m for k, m in code_status.items() if m['status'] == status
            }

        # talk to the user
        print(
            f"\n"
            f"Status:\n"
            f"\t- Modules to update ({len(modules['BEHIND'])}):" +
            f"\n\t\t-".join([''] + list(modules['BEHIND'].keys())) +
            f"\n"
            f"\t- Modules up-to-date ({len(modules['UPDATED'])}):" +
            f"\n\t\t-".join([''] + list(modules['UPDATED'].keys())) +
            f"\n"
            f"\t- Modules ahead of the remote counterpart ({len(modules['AHEAD'])}):" +
            f"\n\t\t-".join([''] + list(modules['AHEAD'].keys())) +
            f"\n"
        )
        if len(modules['BEHIND']) == 0:
            dtslogger.info('Nothing to do.')
            return

        # there is something to update
        granted = ask_confirmation(
            f"{len(modules['BEHIND'])} modules will be updated",
            question="Do you want to continue?",
            default='n'
        )

        if not granted:
            dtslogger.info("Sure, I won't update then.")
            return

        # start update
        try:
            for module in modules['BEHIND']:
                try:
                    dtslogger.info(f"Updating module `{module}`...")
                    update_url = DTCommand.get_code_api_url(hostname, f'module/update/{module}')
                    try:
                        dtslogger.debug(f'GET: "{update_url}"')
                        res = requests.get(update_url, timeout=5)
                        data = res.json()
                        if data['status'] == 'error':
                            dtslogger.warning(data['message'])
                            dtslogger.warning(f"Skipping update for module `{module}`.")
                            continue
                        if data['status'] != 'ok':
                            dtslogger.warning(f'Error occurred while updating module `{module}`.')
                            dtslogger.warning(f"Skipping update for module `{module}`.")
                            continue
                    except requests.exceptions.RequestException:
                        pass
                    # allow some time for the code-api to pick up the action
                    time.sleep(2)
                    # start monitoring update
                    res = DTCommand.monitor_update(hostname, module)
                    if not res:
                        raise requests.exceptions.RequestException()
                    dtslogger.info(f"Module `{module}` successfully updated!")
                except requests.exceptions.RequestException:
                    dtslogger.error(f"An error occurred while updating the module `{module}`.")
                    continue
        except KeyboardInterrupt:
            dtslogger.info("Aborted")
            return
        print()

    @staticmethod
    def get_code_api_url(hostname, resource):
        return f"http://{hostname}/code/{resource}"

    @staticmethod
    def monitor_update(hostname, module):
        url = DTCommand.get_code_api_url(hostname, f"modules/status")
        dtslogger.debug(f'GET(loop): "{url}"')
        pbar = ProgressBar()
        while True:
            try:
                res = requests.get(url, timeout=5)
                code_status = res.json()['data']
                if module not in code_status:
                    dtslogger.error(f"Module `{module}` not found. Skipping.")
                    return False
                if code_status[module]['status'] == 'UPDATED':
                    pbar.done()
                    return True
                if code_status[module]['status'] != 'UPDATING' or \
                        'progress' not in code_status[module]:
                    time.sleep(1)
                    continue
                pbar.set_header(code_status[module]['status_txt'] or 'Updating')
                pbar.update(code_status[module]['progress'])
            except requests.exceptions.RequestException:
                pass
            time.sleep(1)
        pbar.done()
        return False
