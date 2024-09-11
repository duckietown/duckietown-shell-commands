PARTITION_MOUNTPOINT = lambda partition: f"/media/dts/{partition}"
DISK_DEVICE = lambda device, partition_id: f"{device}p{partition_id}"
FILE_PLACEHOLDER_SIGNATURE = "DT_DUCKIETOWN_PLACEHOLDER_"
TMP_WORKDIR = "/tmp/duckietown/dts/disk_image"
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
    {"owner": "duckietown", "module": "portainer"},
    {"owner": "duckietown", "module": "dt-base-environment"},
    {"owner": "duckietown", "module": "dt-commons"},
    {"owner": "duckietown", "module": "dt-device-health"},
    {"owner": "duckietown", "module": "dt-device-online"},
    {"owner": "duckietown", "module": "dt-device-proxy"},
    {"owner": "duckietown", "module": "dt-wifi-access-point"},
    {"owner": "duckietown", "module": "dt-files-api"},
    {"owner": "duckietown", "module": "dt-device-dashboard"},
    {"owner": "duckietown", "module": "dt-ros-commons"},
    {"owner": "duckietown", "module": "dt-duckiebot-interface"},
    {"owner": "duckietown", "module": "dt-rosbridge-websocket"},
    {"owner": "duckietown", "module": "dt-core"},
    {"owner": "duckietown", "module": "dt-code-api"},
    {"owner": "duckietown", "module": "dt-system-monitor"},
    {"owner": "duckietown", "module": "dt-vscode"},
    {"owner": "duckietown", "module": "dtps-switchboard", "tag": "release"},
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
    "mount",
    "umount",
    "touch",
    "chroot",
    "fdisk",
    "gdisk",
    "chmod",
    "rm",
    "docker",
]
