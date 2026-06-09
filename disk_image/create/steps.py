# steps.py

import os
import time
from typing import Set
import yaml
import docker
from disk_image.create.utils import VirtualSDCard
from disk_image.create.constants import PARTITION_MOUNTPOINT, DATA_STORAGE_DISK_IMAGE_DIR
from types import SimpleNamespace

from dt_shell import dtslogger
from typing import Callable

def find_images_in_stack(
    stack_path: str,
    arch: str,
    registry: str,
) -> set:
    """
    Read a stack YAML file, replace any ${ARCH}/{ARCH} and ${REGISTRY}/{REGISTRY}
    placeholders with the given values, and return a set of all `image:` strings
    under `services.*.image`.
    """

    images = set()
    # 1) Load the raw text of the YAML
    with open(stack_path, "r") as f:
        raw_text = f.read()

    # 2) Replace placeholders (both ${FOO} and {FOO} styles)
    raw_text = raw_text.replace("${ARCH}", arch).replace("{ARCH}", arch)
    raw_text = raw_text.replace("${REGISTRY}", registry).replace("{REGISTRY}", registry)

    data = yaml.safe_load(raw_text)

    # If your stack uses a `services:` section, each service can have an `image:` key.
    services = data.get("services", {})
    if isinstance(services, dict):
        for svc_name, svc_def in services.items():
            if not isinstance(svc_def, dict):
                continue
            img = svc_def.get("image")
            if isinstance(img, str):
                images.add(img)

            # You might also have `build:` sections or other fields, but typically we just want
            # explicit `image:` lines. Adapt if your stacks have a different structure.
    return images


def step_docker(
    sd_card: VirtualSDCard,
    out_file_path: Callable[[str], str],
    ROOT_PARTITION: str,
    STACKS: list,
    STACKS_BASE_DIR: str,
    DEVICE_PLATFORM: str,
    DIND_IMAGE_NAME: str,
    architecture: str,
    registry: str = "docker.io"
):
    """
    Mounts the root partition of `sd_card`, starts a Docker-in-Docker (DIND) engine whose
    /var/lib/docker is bind-mounted into the new root, and then pre-pulls every image
    found in the YAML stacks listed in STACKS. Finally, it stops the DIND container
    and unmounts.
    
    Arguments:
        sd_card                - a VirtualSDCard instance, already pointing to out_file_path("img").
        out_file_path          - a function f(ext) -> absolute path of the built disk image.
        ROOT_PARTITION (str)   - the name of the partition to mount (e.g. "APP").
        STACKS (list of str)   - e.g. ["robot/basics", "duckietown/duckiebot", "ros1/duckiebot"].
        STACKS_BASE_DIR (str)   - base directory where `<stack>.yaml` lives.
        DEVICE_PLATFORM (str)   - e.g. "linux/arm64".
        DIND_IMAGE_NAME (str)   - e.g. "docker:24.0.2-dind".
        architecture (str)      - e.g. "arm64v8" used for duckietown-specific tags.
        registry (str)          - Docker registry URL to be used to pull the image from.
    """

    try:
        # 1) Ensure the disk is mounted
        if not sd_card.is_mounted():
            dtslogger.warning(f"The disk {out_file_path('img')} is not mounted.")
        partition_disk = sd_card.partition_device(ROOT_PARTITION)
        if not os.path.exists(partition_disk):
            raise ValueError(f"Disk device {partition_disk} not found")

        sd_card.mount_partition(ROOT_PARTITION)

        # 2) Start a DIND container whose /var/lib/docker points into the new root
        local_docker = docker.from_env()

        # Stop and remove any leftover DIND container from a previous session
        try:
            old_container = local_docker.containers.get("dts-disk-image-aux-docker")
            dtslogger.warning("Found leftover DIND container from previous session, stopping it...")
            old_container.stop()
            old_container.remove(force=True)
        except docker.errors.NotFound:
            pass

        # Pull the DIND image locally, if needed
        try:
            local_docker.images.get(DIND_IMAGE_NAME)
            dtslogger.debug(f"DIND image `{DIND_IMAGE_NAME}` already present locally.")
        except docker.errors.ImageNotFound:
            dtslogger.info(f"Pulling DIND image `{DIND_IMAGE_NAME}`…")
            local_docker.images.pull(DIND_IMAGE_NAME)

        remote_docker_dir = os.path.join(
            PARTITION_MOUNTPOINT(ROOT_PARTITION), "var", "lib", "docker"
        )

        # Launch DIND, publishing port 2375 so we can connect
        remote_docker_engine_container = local_docker.containers.run(
            image=DIND_IMAGE_NAME,
            detach=True,
            remove=True,
            auto_remove=True,
            publish_all_ports=True,
            privileged=True,
            name="dts-disk-image-aux-docker",
            volumes={remote_docker_dir: {"bind": "/var/lib/docker", "mode": "rw"}},
            entrypoint=["dockerd", "--host=tcp://0.0.0.0:2375", "--bridge=none"],
        )

        dtslogger.info("Waiting 20 seconds for DIND to start inside the image…")
        time.sleep(20)

        # Inspect the container to get its IP (so we can connect to port 2375)
        container_info = local_docker.api.inspect_container("dts-disk-image-aux-docker")
        container_ip = container_info["NetworkSettings"]["Networks"]["bridge"]["IPAddress"]
        endpoint_url = f"tcp://{container_ip}:2375"

        dtslogger.info(f"DIND is up—connecting to remote Docker at {endpoint_url}")
        remote_docker = docker.DockerClient(base_url=endpoint_url)

        # 3) Collect all image names from each stack YAML
        abs_stacks_dir = os.path.abspath(STACKS_BASE_DIR)
        all_stack_images : Set[str] = set()

        for stack in STACKS:
            stack_path = os.path.join(abs_stacks_dir, stack + ".yaml")
            if not os.path.isfile(stack_path):
                dtslogger.warning(f"Stack file not found: {stack_path}.  Skipping.")
                continue
            try:
                images_in_this = find_images_in_stack(stack_path, architecture, registry)
                dtslogger.debug(f"Stack `{stack}` → images: {images_in_this}")
                all_stack_images.update(images_in_this)
            except Exception as e:
                dtslogger.warning(f"Could not parse `{stack_path}`: {e}")

        dtslogger.info(f"Trying to pull the following images: {all_stack_images}")
        # 4) Pull each discovered image into the remote (DIND) daemon
        if all_stack_images:
            dtslogger.info(f"Transferring {len(all_stack_images)} Docker images into the disk…")
            for img_name in sorted(all_stack_images):
                dtslogger.info(f"  · Pulling {img_name}…")
                try:
                    remote_docker.images.pull(img_name, platform=DEVICE_PLATFORM)
                except Exception as e:
                    dtslogger.warning(f"    ↳ failed to pull {img_name}: {e}")
            dtslogger.info("Finished transferring all stack images.")
        else:
            dtslogger.info("No images found in any STACKS—skipping pre-pull.")

    except Exception as e:
        # If anything errors out, make sure to unmount and re-raise
        dtslogger.error(f"Error during `docker` step: {e}")
        sd_card.umount()
        raise

    finally:
        # Stop the DIND container (if it exists) and unmount the partition
        try:
            remote_docker_engine_container.stop()
        except Exception:
            pass
        try:
            sd_card.umount_partition(ROOT_PARTITION)
        except Exception:
            pass

def step_push(shell, out_file_name, out_file_path):
    dtslogger.info("Step BEGIN: push")
    dtslogger.info("Pushing disk image...")
    shell.include.data.push.command(
            shell,
            [],
            parsed=SimpleNamespace(
                file=[out_file_path],
                object=[os.path.join(DATA_STORAGE_DISK_IMAGE_DIR, out_file_name)],
                space="public",
                token=shell.profile.secrets.dt_token,
                compress=False,
            ),
        )
    dtslogger.info("Done!")
    dtslogger.info("Step END: push\n")