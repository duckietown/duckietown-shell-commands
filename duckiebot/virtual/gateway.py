import fcntl
import ipaddress
import json
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path

from utils.duckietown_utils import USER_DATA_DIR

GATEWAY_LEADER_LABEL = "org.duckietown.virtual-device.gateway-leader"
GATEWAY_LEADER_LABEL_VALUE = "1"
VIRTUAL_ROBOT_CONTAINER_PREFIX = "dts-virtual-"
GATEWAY_LOCK_PATH = Path(USER_DATA_DIR) / "virtual_robots" / "gateway.lock"
GATEWAY_STATE_DIRECTORY = Path(USER_DATA_DIR) / "virtual_robots" / "gateway"
GATEWAY_BACKENDS_FILENAME = "backends.json"
GATEWAY_STATE_MOUNT = "/host-gateway-state"
ROBOT_NAME_PATTERN = re.compile(r"[a-z][a-z0-9]*")
GATEWAY_PORT_MAPPINGS = [
    ["80", "18080", "tcp"],
    ["8080", "18081", "tcp"],
    ["9001", "19001", "tcp"],
    ["11411", "21411", "tcp"],
    ["11911", "21911", "tcp"],
]


@contextmanager
def gateway_leader_election():
    lock_directory = GATEWAY_LOCK_PATH.parent
    lock_directory.mkdir(parents=True, exist_ok=True)
    lock_file = GATEWAY_LOCK_PATH.open("w")
    lock_file_descriptor = lock_file.fileno()
    fcntl.flock(lock_file_descriptor, fcntl.LOCK_EX)
    try:
        yield
    finally:
        fcntl.flock(lock_file_descriptor, fcntl.LOCK_UN)
        lock_file.close()


def should_start_gateway(local_docker):
    containers = local_docker.containers
    running_containers = containers.list()
    for container in running_containers:
        if is_gateway_leader(container):
            return False
    return True


def is_gateway_leader(container):
    attributes = container.attrs
    config = attributes.get("Config", {})
    labels = config.get("Labels", {})
    if labels is None:
        labels = {}
    leader_value = labels.get(GATEWAY_LEADER_LABEL)
    return leader_value == GATEWAY_LEADER_LABEL_VALUE


def gateway_leader_options():
    state_directory = _ensure_gateway_state_directory()
    environment = {
        "DT_FLEET_GATEWAY": "1",
    }
    labels = {GATEWAY_LEADER_LABEL: GATEWAY_LEADER_LABEL_VALUE}
    state_volume = (str(state_directory), GATEWAY_STATE_MOUNT, "ro")
    return environment, labels, state_volume


def refresh_gateway_backends(local_docker):
    containers = local_docker.containers
    running_containers = containers.list()
    backend_records = []
    for container in running_containers:
        backend_record = _gateway_backend_record(container)
        if backend_record is not None:
            backend_records.append(backend_record)
    backend_records.sort(key=_gateway_backend_name)
    _write_gateway_backends(backend_records)


def has_other_virtual_robots(local_docker, robot_name):
    containers = local_docker.containers
    running_containers = containers.list()
    for container in running_containers:
        container_name = container.name
        is_virtual_robot = container_name.startswith(VIRTUAL_ROBOT_CONTAINER_PREFIX)
        is_requested_robot = container_name == f"{VIRTUAL_ROBOT_CONTAINER_PREFIX}{robot_name}"
        if is_virtual_robot and not is_requested_robot:
            return True
    return False


def _ensure_gateway_state_directory():
    state_directory = GATEWAY_STATE_DIRECTORY
    state_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    state_directory.chmod(0o700)
    state_path = state_directory / GATEWAY_BACKENDS_FILENAME
    if not state_path.exists():
        state_path.write_text("[]\n", encoding="utf-8")
        state_path.chmod(0o600)
    return state_directory


def _gateway_backend_record(container):
    container_name = container.name
    robot_name = _remove_virtual_robot_prefix(container_name)
    if robot_name is None:
        return None

    attributes = container.attrs
    network_settings = attributes.get("NetworkSettings", {})
    networks = network_settings.get("Networks", {})
    network_values = networks.values()
    for network in network_values:
        raw_address = network.get("IPAddress")
        if not raw_address:
            continue
        try:
            address = ipaddress.ip_address(raw_address)
        except ValueError:
            continue
        if address.version != 4:
            continue
        normalized_address = str(address)
        return {"name": robot_name, "address": normalized_address}
    return None


def _remove_virtual_robot_prefix(container_name):
    if not container_name.startswith(VIRTUAL_ROBOT_CONTAINER_PREFIX):
        return None
    prefix_length = len(VIRTUAL_ROBOT_CONTAINER_PREFIX)
    robot_name = container_name[prefix_length:]
    if ROBOT_NAME_PATTERN.fullmatch(robot_name) is None:
        return None
    return robot_name


def _gateway_backend_name(backend_record):
    return backend_record["name"]


def _write_gateway_backends(backend_records):
    state_directory = _ensure_gateway_state_directory()
    backend_state_path = state_directory / GATEWAY_BACKENDS_FILENAME
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=state_directory,
        prefix=f"{GATEWAY_BACKENDS_FILENAME}.",
        suffix=".tmp",
        delete=False,
    ) as temporary_file:
        temporary_file_name = temporary_file.name
        temporary_path = Path(temporary_file_name)
        json.dump(backend_records, temporary_file, sort_keys=True)
        temporary_file.write("\n")
    temporary_path.chmod(0o600)
    temporary_path.replace(backend_state_path)
