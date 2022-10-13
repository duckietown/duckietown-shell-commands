import os
import platform
import stat
from pathlib import Path

import requests
from dt_shell import UserError

from pydock import DockerClient

from .misc_utils import parse_version

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
    from .dtproject_utils import CANONICAL_ARCH
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


def ensure_buildx_version(client: DockerClient, v: str):
    version = client.buildx.version()
    vnow_str = version['version']
    vnow = parse_version(vnow_str)
    if v.endswith("+"):
        vneed_str = v.rstrip("+")
        vneed = parse_version(vneed_str)
        if vnow < vneed:
            msg = f"""

Detected Docker Buildx {vnow_str} but this command needs Docker Buildx >= {vneed_str}.
Please, update your Docker Buildx before continuing.
            
            """
            raise UserError(msg)
    else:
        vneed = parse_version(v)
        if vnow != vneed:
            msg = f"""

Detected Docker Buildx {vnow_str} but this command needs Docker Buildx == {v}.
Please, install the correct version before continuing.
            
            """
            raise UserError(msg)
