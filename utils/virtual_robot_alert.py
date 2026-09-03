import time
from datetime import datetime

try:
    import docker
except ImportError:
    docker = None

from dt_shell import dtslogger
from dt_shell.shell import EventType

INITIAL_ALERT_INTERVAL_SECONDS = 60 * 60  # 1 hour
RUNNING_VIRTUAL_ROBOT_ALERTS_DATABASE_KEY = "running_virtual_robot_alerts"
VIRTUAL_ROBOT_CONTAINER_PREFIX = "dts-virtual-"


class _RunningVirtualRobotAlertHandler:
    def __init__(self, shell) -> None:
        self._shell = shell

    def __call__(self, _event) -> None:
        warn_about_running_virtual_robots(self._shell)


def register_running_virtual_robot_alert(shell) -> None:
    if shell is None or getattr(shell, "_readonly", False):
        return
    handler = _RunningVirtualRobotAlertHandler(shell)
    shell.on_event(EventType.POST_COMMAND_IMPORT, handler)


def warn_about_running_virtual_robots(shell, docker_client=None, now: float | None = None) -> None:
    if docker is None:
        return
    try:
        client = docker_client or docker.from_env()
        containers_client = client.containers
        containers = containers_client.list(filters={
            "status": "running",
        })
    except docker.errors.DockerException:
        return

    current_time = time.time() if now is None else now
    updates_check_db = shell.updates_check_db
    raw_states = updates_check_db.get(RUNNING_VIRTUAL_ROBOT_ALERTS_DATABASE_KEY, {})
    states: dict[str, dict] = raw_states if isinstance(raw_states, dict) else {}
    updated_states: dict[str, dict] = {}
    alerted_robots: list[str] = []

    for container, robot_name, started_at in _running_virtual_robots(containers):
        session_key = _container_session_key(container, robot_name, started_at)
        state = states.get(session_key, {})
        if not isinstance(state, dict):
            state = {}
        if _alert_is_due(started_at, state, current_time):
            state = _record_alert(state, current_time)
            alerted_robots.append(robot_name)
        if state:
            updated_states[session_key] = state

    if updated_states != raw_states:
        updates_check_db.set(RUNNING_VIRTUAL_ROBOT_ALERTS_DATABASE_KEY, updated_states)
    if alerted_robots:
        alerted_robot_names = sorted(alerted_robots)
        warning_message = _warning_message(alerted_robot_names)
        dtslogger.warning(warning_message)


def _running_virtual_robots(containers) -> list[tuple[object, str, float]]:
    running_robots: list[tuple[object, str, float]] = []
    for container in containers:
        robot_name = getattr(container, "name", "")
        if not robot_name.startswith(VIRTUAL_ROBOT_CONTAINER_PREFIX):
            continue
        try:
            container.reload()
        except docker.errors.DockerException:
            continue
        attributes = getattr(container, "attrs", {})
        state = attributes.get("State", {})
        if not isinstance(state, dict) or state.get("Running") is False:
            continue
        started_at = _parse_started_at(state.get("StartedAt"))
        if started_at is None:
            continue
        robot_name = robot_name[len(VIRTUAL_ROBOT_CONTAINER_PREFIX) :]
        running_robots.append((container, robot_name, started_at))
    return running_robots


def _parse_started_at(started_at: str | None) -> float | None:
    if not isinstance(started_at, str):
        return None
    try:
        normalized_started_at = started_at.replace("Z", "+00:00")
        started_datetime = datetime.fromisoformat(normalized_started_at)
        return started_datetime.timestamp()
    except (OSError, OverflowError, ValueError):
        return None


def _container_session_key(container, robot_name: str, started_at: float) -> str:
    container_id = getattr(container, "id", None)
    return container_id or f"{robot_name}:{started_at}"


def _alert_is_due(started_at: float, state: dict, current_time: float) -> bool:
    alerts_sent = _alerts_sent(state)
    if alerts_sent == 0:
        return current_time - started_at >= INITIAL_ALERT_INTERVAL_SECONDS
    last_alert_at = state.get("last_alert_at")
    if not isinstance(last_alert_at, (int, float)):
        return True
    interval = INITIAL_ALERT_INTERVAL_SECONDS * 2**alerts_sent
    return current_time - last_alert_at >= interval


def _alerts_sent(state: dict) -> int:
    alerts_sent = state.get("alerts_sent", 0)
    if not isinstance(alerts_sent, int) or alerts_sent < 0:
        return 0
    return alerts_sent


def _record_alert(state: dict, current_time: float) -> dict:
    alerts_sent = _alerts_sent(state)
    return {
        "alerts_sent": alerts_sent + 1,
        "last_alert_at": current_time,
    }


def _warning_message(robot_names: list[str]) -> str:
    if len(robot_names) == 1:
        robot_name = robot_names[0]
        return (
            f"Virtual robot '{robot_name}' is still running. "
            f"Stop it with 'dts duckiebot virtual stop {robot_name}' when it is no longer needed."
        )
    commands = "\n".join(f"  dts duckiebot virtual stop {robot_name}" for robot_name in robot_names)
    return (
        f"Virtual robots {', '.join(repr(robot_name) for robot_name in robot_names)} are still running. "
        f"Stop them when they are no longer needed:\n{commands}"
    )
