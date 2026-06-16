from typing import Iterable

from utils.host_runner import HostRunnerError, delegate_command_to_host, should_delegate_to_host


def should_delegate_matrix_run() -> bool:
    return should_delegate_to_host()


def delegate_matrix_run_to_host(args: Iterable[str]) -> int:
    return delegate_command_to_host(("matrix", "run"), args)
