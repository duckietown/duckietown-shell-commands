import os


PARTITION_MOUNTPOINT = lambda partition: f"/media/dts/{partition}"
DISK_DEVICE = lambda device, partition_id: f"{device}p{partition_id}"
FILE_PLACEHOLDER_SIGNATURE = "DT_DUCKIETOWN_PLACEHOLDER_"
LEGACY_TMP_WORKDIR = "/tmp/duckietown/dts/disk_image"
HOME_DIR = os.path.expanduser("~")
FALLBACK_TMP_WORKDIR = os.path.join(HOME_DIR, ".cache", "duckietown", "dts", "disk_image")


def _get_existing_parent_dir(path: str) -> str:
    parent_dir = path
    while not os.path.isdir(parent_dir):
        next_parent_dir = os.path.dirname(parent_dir)
        if next_parent_dir == parent_dir:
            break
        parent_dir = next_parent_dir
    return parent_dir


def _can_create_workdir(path: str) -> bool:
    existing_parent_dir = _get_existing_parent_dir(path)
    required_mode = os.W_OK | os.X_OK
    return os.access(existing_parent_dir, required_mode)


def _get_tmp_workdir() -> str:
    candidate_dirs = (LEGACY_TMP_WORKDIR, FALLBACK_TMP_WORKDIR)
    for workdir in candidate_dirs:
        if _can_create_workdir(workdir):
            return workdir
    raise OSError("Could not determine a writable disk image working directory.")


TMP_WORKDIR = _get_tmp_workdir()
DISK_IMAGE_STATS_LOCATION = "data/stats/disk_image/build.json"
DATA_STORAGE_DISK_IMAGE_DIR = "disk_image"
DEFAULT_STACK = "duckietown"
AUTOBOOT_STACKS_DIR = "/data/autoboot/"
DEFAULT_DEVICE_ARCH = "arm64v8"
DEFAULT_DOCKER_REGISTRY = "docker.io"
DOCKER_IMAGE_TEMPLATE = (
    lambda owner, module, tag=None, version=None, arch=DEFAULT_DEVICE_ARCH, registry=DEFAULT_DOCKER_REGISTRY:
        f"{registry}/{owner}/{module}:" + (f"{version}-{arch}" if tag is None else tag)
)

MODULES_TO_LOAD = [
    {"owner": "duckietown", "module": "dt-base-environment"},
    {"owner": "duckietown", "module": "dt-code-api"},
    {"owner": "duckietown", "module": "dt-commons"},
    {"owner": "duckietown", "module": "dt-core"},
    {"owner": "duckietown", "module": "dt-device-dashboard"},
    {"owner": "duckietown", "module": "dt-device-health"},
    {"owner": "duckietown", "module": "dt-device-online"},
    {"owner": "duckietown", "module": "dt-device-proxy"},
    {"owner": "duckietown", "module": "dt-duckiebot-interface"},
    {"owner": "duckietown", "module": "dt-files-api"},
    {"owner": "duckietown", "module": "dt-kvstore"},
    {"owner": "duckietown", "module": "dt-ros-commons"},
    {"owner": "duckietown", "module": "dt-ros-interface"},
    {"owner": "duckietown", "module": "dt-ros2-commons"},
    {"owner": "duckietown", "module": "dt-ros2-interface"},
    {"owner": "duckietown", "module": "dt-rosbridge-websocket"},
    {"owner": "duckietown", "module": "dt-system-monitor"},
    {"owner": "duckietown", "module": "dt-vscode"},
    {"owner": "duckietown", "module": "dt-wifi-access-point"},
    {"owner": "duckietown", "module": "dtps-switchboard", "tag": "release"},
    {"owner": "duckietown", "module": "portainer"},
]

CLI_TOOLS_NEEDED = [
    "wget",
    "unzip",
    "sudo",
    "cp",
    "sha256sum",
    "strings",
    "grep",
    "stat",
    "udevadm",
    "losetup",
    "parted",
    "e2fsck",
    "resize2fs",
    "truncate",
    "mkfs.fat",
    "fatlabel",
    "mount",
    "umount",
    "touch",
    "chroot",
    "fdisk",
    "gdisk",
    "mknod",
    "chmod",
    "rm",
    "docker",
]
