import argparse

from docker.errors import APIError

from dt_shell import DTCommandAbs, DTShell, dtslogger
from utils.cli_utils import ask_confirmation
from utils.docker_utils import get_client
from dtproject.utils.misc import dtlabel
from utils.misc_utils import sanitize_hostname
from utils.robot_utils import log_event_on_robot


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts duckiebot clean"
        parser = argparse.ArgumentParser(prog=prog)
        # define arguments
        parser.add_argument(
            "-a", "--all", action="store_true", default=False, help="Delete all unused images"
        )
        parser.add_argument(
            "--no-official",
            action="store_true",
            default=False,
            help="Do NOT delete official Duckietown images",
        )
        parser.add_argument(
            "--untagged", action="store_true", default=False, help="Delete only untagged images"
        )
        parser.add_argument(
            "-y", "--yes", action="store_true", default=False, help="Do not ask for confirmation"
        )
        parser.add_argument("robot", nargs=1, help="Name of the Robot to clean")
        # parse arguments
        parsed = parser.parse_args(args)
        # sanitize arguments
        parsed.robot = parsed.robot[0]
        hostname = sanitize_hostname(parsed.robot)
        # open connection to robot
        client = get_client(hostname)
        client.info()
        # it looks like the clean is going to happen, mark the event
        log_event_on_robot(parsed.robot, "duckiebot/clean")
        # fetch list of stopped containers
        dtslogger.info("Fetching list of containers...")
        containers_filters = {"status": "exited"}
        all_containers = client.containers.list(all=True)
        containers = client.containers.list(all=True, filters=containers_filters)
        dtslogger.info(f"Removing {len(containers)} containers.")
        dtslogger.debug(
            "Removing containers:\n\t"
            + "\n\t".join([f"[{container.short_id}] {container.name}" for container in containers])
        )
        # fetch list of dangling images on the robot
        dtslogger.info("Fetching list of images...")
        images_filters = {"dangling": True}
        if parsed.all:
            # no more filters
            pass
        else:
            # authoritative images only
            images_filters["label"] = f"{dtlabel('image.authoritative')}=1"
        all_images = client.images.list(all=True)
        images = client.images.list(all=True, filters=images_filters)
        # find unused images
        for image in all_images:
            # handle official Duckietown images
            if parsed.no_official:
                if (
                    dtlabel("image.authoritative") in image.labels
                    and image.labels[dtlabel("image.authoritative")] == "1"
                ):
                    dtslogger.debug(f"Ignoring image '{image.id}' as it is an official image")
                    continue
            # only untagged?
            if parsed.untagged:
                if len(image.tags) > 0:
                    dtslogger.debug(f"Ignoring image '{image.id}' as it is tagged")
                    continue
            used = False
            for container in all_containers:
                if container in containers:
                    continue
                if image.id == container.image.id:
                    used = True
                    break
            if not used:
                images.append(image)
        # keep only unique images
        images = list({image.id: image for image in images}.values())
        dtslogger.info(f"Removing {len(images)} images.")
        dtslogger.debug(
            "Removing images:\n\t"
            + "\n\t".join([f"[{image.short_id}] {','.join(image.tags)}" for image in images])
        )
        # exit if there is nothing to do
        if len(containers) + len(images) <= 0:
            dtslogger.info("Nothing to do")
            return
        # ask for confirmation (if not instructed not to)
        if not parsed.yes:
            granted = ask_confirmation("This cannot be undone")
            if not granted:
                dtslogger.error("User aborted.")
                return
        # do clean
        for container in containers:
            dtslogger.info(f"Removing container [{container.short_id}] {container.name}...")
            container.remove()
        already_removed = set()
        while True:
            removed = 0
            for image in images:
                if image.id in already_removed:
                    continue
                dtslogger.info(f"Removing image [{image.short_id}] {','.join(image.tags)}...")
                try:
                    client.images.remove(image=image.id, force=True)
                    already_removed.add(image.id)
                    removed += 1
                except APIError:
                    pass
            if removed <= 0:
                break
