import argparse

from dt_shell import DTCommandAbs, DTShell, dtslogger
from utils.docker_utils import (
    DEFAULT_MACHINE,
    get_client,
    get_endpoint_architecture,
    get_registry_to_use,
    login_client_OLD,
    pull_image,
)
from utils.duckietown_utils import get_distro_version

OTHER_IMAGES_TO_UPDATE = [
    "{registry}/duckietown/dt-gui-tools:{distro}-{arch}",
    "{registry}/duckietown/dt-core:{distro}-{arch}",
    "{registry}/duckietown/dt-duckiebot-fifos-bridge:{distro}-{arch}",
    "{registry}/duckietown/challenge-aido_lf-baseline-duckietown:{distro}-{arch}",
    "{registry}/duckietown/challenge-aido_lf-baseline-duckietown-ml:{distro}-{arch}",
    "{registry}/duckietown/challenge-aido_lf-template-ros:{distro}-{arch}",
    "{registry}/duckietown/challenge-aido_lf-simulator-gym:{distro}-{arch}",
    "{registry}/duckietown/aido-base-python3:{distro}-{arch}",
]


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts desktop update"
        parser = argparse.ArgumentParser(prog=prog)

        # parse arguments
        parsed = parser.parse_args(args)

        registry_to_use = get_registry_to_use()

        # compile image names
        arch = get_endpoint_architecture(DEFAULT_MACHINE)
        distro = get_distro_version(shell)
        images = [
            img.format(registry=registry_to_use, distro=distro, arch=arch) for img in OTHER_IMAGES_TO_UPDATE
        ]
        client = get_client()
        login_client_OLD(client, shell.shell_config, registry_to_use, raise_on_error=False)
        # do update
        for image in images:
            dtslogger.info(f"Pulling image `{image}`...")
            pull_image(image, client)
