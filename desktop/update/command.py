import argparse

from dt_shell import DTCommandAbs, DTShell, dtslogger
from utils.docker_utils import get_endpoint_architecture, get_client, pull_image, DEFAULT_MACHINE, \
    DEFAULT_REGISTRY, STAGING_REGISTRY
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
        # define arguments
        parser.add_argument(
            "--stage",
            "--staging",
            dest="staging",
            action="store_true",
            default=False,
            help="Use staging code"
        )
        parser.add_argument(
            "--registry",
            type=str,
            default=DEFAULT_REGISTRY,
            help="Use images from this Docker registry",
        )
        # parse arguments
        parsed = parser.parse_args(args)
        # staging
        if parsed.staging:
            parsed.registry = STAGING_REGISTRY
        # registry
        if parsed.registry != DEFAULT_REGISTRY:
            dtslogger.info(f"Using custom registry: {parsed.registry}")
        # compile image names
        arch = get_endpoint_architecture(DEFAULT_MACHINE)
        distro = get_distro_version(shell)
        images = [img.format(registry=parsed.registry, distro=distro, arch=arch)
                  for img in OTHER_IMAGES_TO_UPDATE]
        client = get_client()
        # do update
        for image in images:
            dtslogger.info(f"Pulling image `{image}`...")
            pull_image(image, client)
