import os
import platform
import stat
from pathlib import Path

import requests

DOCKER_INFO = """
Docker Endpoint:
  Hostname: {name}
  Operating System: {operating_system}
  Kernel Version: {kernel_version}
  OSType: {os_type}
  Architecture: {architecture}
  Total Memory: {mem_total}
  CPUs: {n_cpu}
"""

DEFAULT_BUILDX_VERSION = "0.9.1"


def install_buildx(version: str = DEFAULT_BUILDX_VERSION):
    from utils.dtproject_utils import CANONICAL_ARCH
    version = version.lstrip("v")
    # get machine architecture
    machine = platform.machine()
    if machine not in CANONICAL_ARCH:
        raise ValueError(f"Architecture not supported '{machine}'")
    arch = {
        "amd64": "amd64",
        "arm32v7": "arm-v7",
        "arm64v8": "arm64"
    }[CANONICAL_ARCH[machine]]
    # get machine OS
    system = platform.system().lower()
    # compile URL
    url = f"https://github.com/docker/buildx/releases/download/v{version}/buildx-v{version}.{system}-{arch}"
    # define destination
    destination = os.path.expanduser("~/.docker/cli-plugins")
    os.makedirs(destination, exist_ok=True)
    local = os.path.join(destination, "docker-buildx")
    # download binary
    with open(local, "wb") as fout:
        fout.write(requests.get(url).content)
    # make binary executable
    f = Path(local)
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
