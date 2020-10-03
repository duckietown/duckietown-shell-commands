import io
import re
import sys
import copy
import argparse

from collections import OrderedDict
from termcolor import colored
from datetime import datetime
from threading import Thread, Semaphore

from dt_shell import DTCommandAbs, dtslogger, DTShell
from utils.docker_utils import get_client, get_endpoint_architecture_from_ip, get_remote_client
from utils.dtproject_utils import dtlabel, DTProject
from utils.cli_utils import ProgressBar, ask_confirmation
from utils.duckietown_utils import get_distro_version
from utils.networking_utils import get_duckiebot_ip


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts duckiebot update"
        parser = argparse.ArgumentParser(prog=prog)
        # define arguments
        parser.add_argument(
            "-a",
            "--all",
            default=False,
            action="store_true",
            help="Update all Duckietown modules (only official code is updated by default)",
        )
        parser.add_argument(
            "-D",
            "--distro",
            default=get_distro_version(shell),
            help="Only update images of this Duckietown distro",
        )
        parser.add_argument("hostname", nargs=1, help="Name of the Duckiebot to check software status for")
        # parse arguments
        parsed = parser.parse_args(args)
        hostname = parsed.hostname[0]

        # open Docker client
        duckiebot_ip = get_duckiebot_ip(hostname)
        docker = get_remote_client(duckiebot_ip)
#        docker = get_client(hostname)
        arch = get_endpoint_architecture_from_ip(duckiebot_ip)
        image_pattern = re.compile(f"^duckietown/.+:{get_distro_version(shell)}-{arch}$")

        # fetch list of images at the Docker endpoint
        dtslogger.info("Fetching software status from your Duckiebot...")
        images = docker.images.list()

        # we only update official duckietown images
        images = [
            image
            for image in images
            if len(image.tags) > 0
            and image_pattern.match(image.tags[0])
            and (parsed.all or image.labels.get(dtlabel("image.authoritative"), "0") == "1")
        ]
        dtslogger.info(f"Found {len(images)} Duckietown software modules. " f"Looking for updates...")
        print()

        updates_monitor = UpdatesMonitor()
        for image in images:
            updates_monitor[image.tags[0]] = ("...", None)

        # check which images need update
        need_update = []
        try:
            for image in images:
                # get image name
                name = image.tags[0]
                # fetch remote image labels
                labels = _get_remote_labels(name)
                if labels is None:
                    # image is not available online
                    updates_monitor[name] = ("not found", None)
                    continue
                # fetch local and remote build time
                updates_monitor[name] = ("checking", None)
                image_time_str = image.labels.get(dtlabel("time"), "ND")
                image_time = _parse_time(image_time_str)
                remote_time = _parse_time(labels[dtlabel("time")]) if dtlabel("time") in labels else "ND"
                # show error, up-to-date or to update
                if remote_time is None:
                    # remote build time could not be fetched, error
                    updates_monitor[name] = ("error", "red")
                    continue
                if image_time is None or image_time < remote_time:
                    # the remote copy is newer than the local, fetch versions
                    version_lbl = dtlabel("code.version.head")
                    local_version = image.labels.get(version_lbl, "devel")
                    remote_version = labels[version_lbl] if version_lbl in labels else "ND"
                    # show OLDv -> NEWv
                    version_transition = (
                        f"({local_version} -> {remote_version})" if remote_version != "ND" else ""
                    )
                    # update monitor
                    updates_monitor[name] = (f"update available {version_transition}", "yellow")
                    need_update.append(name)
                    continue
                else:
                    # module is up-to-date
                    updates_monitor[name] = ("up-to-date", "green")
        except KeyboardInterrupt:
            dtslogger.info("Aborted")
            exit(0)
        print()

        # nothing to do
        if len(need_update) == 0:
            dtslogger.info("Everything up to date!")
            exit(0)

        # ask for confirmation
        granted = ask_confirmation(f" {len(need_update)} module(s) will be updated.")
        if not granted:
            dtslogger.info("Bye!")
            exit(0)
        dtslogger.info("Updating:\n")
        sys.stdout.flush()
        updates_monitor.forget()

        # remove packages that do not need update from the monitor
        for name, (status, _) in copy.deepcopy(list(updates_monitor.items())):
            if status in ["error", "not found", "up-to-date"]:
                del updates_monitor[name]
            else:
                updates_monitor[name] = ("waiting", "yellow")

        # start update
        workers = []
        for image in need_update:
            t = Thread(target=_pull_docker_image, args=(docker, image, updates_monitor))
            workers.append(t)

        # wait for the update to finish
        try:
            for t in workers:
                t.start()
                t.join()
        except KeyboardInterrupt:
            exit(0)
        print()
        dtslogger.info("Update complete!")


def _parse_time(time_iso):
    time = None
    try:
        time = datetime.strptime(time_iso, "%Y-%m-%dT%H:%M:%S.%f")
    except ValueError:
        pass
    return time


def _get_remote_labels(image):
    labels = None
    metadata = None
    try:
        metadata = DTProject.inspect_remote_image(*image.split(":"))
    except KeyboardInterrupt as e:
        raise e
    except BaseException:
        pass
    # ---
    if metadata is not None and isinstance(metadata, dict):
        remote_config = metadata["config"] if "config" in metadata else {}
        labels = remote_config["Labels"] if "Labels" in remote_config else None
    return labels


def _pull_docker_image(client, image, monitor):
    try:
        repository, tag = image.split(":")
        buffer = io.StringIO()
        pbar = ProgressBar(scale=0.3, buf=buffer)
        total_layers = set()
        completed_layers = set()
        for step in client.api.pull(repository, tag, stream=True, decode=True):
            if "status" not in step or "id" not in step:
                continue
            total_layers.add(step["id"])
            if step["status"] in ["Pull complete", "Already exists"]:
                completed_layers.add(step["id"])
            # compute progress
            if len(total_layers) > 0:
                progress = int(100 * len(completed_layers) / len(total_layers))
                pbar.update(progress)
                monitor[image] = (buffer.getvalue().strip("\n"), None)
        pbar.update(100)
        monitor[image] = ("updated", "green")
    except KeyboardInterrupt:
        return


class UpdatesMonitor(OrderedDict):
    def __init__(self):
        super().__init__()
        self._buffer = []
        self._semaphore = Semaphore(1)
        self._quiet = False

    def __setitem__(self, key, value):
        self._semaphore.acquire()
        super(UpdatesMonitor, self).__setitem__(key, value)
        # render
        self._render()
        self._semaphore.release()

    def forget(self):
        self._buffer = []

    def _render(self):
        if self._quiet:
            return
        # clean buffer
        sys.stdout.write("\033[F\033[K" * len(self._buffer))
        sys.stdout.flush()
        self._buffer = []
        # get longest key
        width = max(map(len, self.keys())) + 2
        # populate buffer
        for module, (status, color) in self.items():
            padding = " " * (width - len(module))
            self._buffer.append(f"    {module}:{padding}{colored(status, color)}")
        # write buffer
        print("\n".join(self._buffer))
        sys.stdout.flush()
        sys.stdout.flush()
