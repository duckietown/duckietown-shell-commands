import argparse

from dt_shell import DTCommandAbs, DTShell, dtslogger
from utils.docker_utils import get_endpoint_architecture, get_client, pull_image, DEFAULT_MACHINE
from utils.duckietown_utils import get_distro_version

OTHER_IMAGES_TO_UPDATE = [
    "duckietown/dt-gui-tools:{distro}-{arch}",
    "duckietown/dt-core:{distro}-{arch}",
]


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts desktop update"
        parser = argparse.ArgumentParser(prog=prog)
        # parse arguments
        parsed = parser.parse_args(args)
        # compile image names
        arch = get_endpoint_architecture(DEFAULT_MACHINE)
        distro = get_distro_version(shell)
        images = [img.format(distro=distro, arch=arch) for img in OTHER_IMAGES_TO_UPDATE]
        client = get_client()
        # do update
        for image in images:
            dtslogger.info(f"Pulling image `{image}`...")
            pull_image(image, client)
