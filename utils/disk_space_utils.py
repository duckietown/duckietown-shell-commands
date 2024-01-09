import sys
import shutil
from typing import Union, Optional

from dt_shell import dtslogger


_DISK_ROOT_PATH = "/"
# margin to spare, the less of the two is used

# _DISK_SPACE_MARGIN_PERC = 1.0  # 1% of total disk
# _DISK_SPACE_MARGIN_BYTES_ABS = (2 ** 20) * 500  # 500 MB

# strict comparison
_DISK_SPACE_MARGIN_PERC = 0.0
_DISK_SPACE_MARGIN_BYTES_ABS = 0

# KB, MB, GB
_CONST_NUM_BYTES_IN_KB = 2**10
_CONST_NUM_BYTES_IN_MB = _CONST_NUM_BYTES_IN_KB**2
_CONST_NUM_BYTES_IN_GB = _CONST_NUM_BYTES_IN_KB**3


def check_enough_disk(value: Union[str, float]) -> Optional[bool]:
    """Whether the local disk space is enough given the demanded value

    Args:
        value (Union[str, float]): number of Bytes required

    Returns:
        Optional[bool]: if not None, disk space satisfied or not. If None, error
    """

    # TODO: windows?
    try:
        stats = shutil.disk_usage(_DISK_ROOT_PATH)
        margin_by_perc = _DISK_SPACE_MARGIN_PERC / 100.0 * stats.total
        margin = min(margin_by_perc, _DISK_SPACE_MARGIN_BYTES_ABS)
        dtslogger.debug(f"Disk stats: {stats}")
        if float(value) + margin <= stats.free:
            return True
        else:
            return False
    except Exception as exc:
        dtslogger.warning(
            f"Unable to determine whether sufficient disk space is present. Error details: {exc}"
        )


def num_bytes_to_simple_friendly_str(num_bytes: int) -> str:
    f_n = float(num_bytes)
    res = f_n / _CONST_NUM_BYTES_IN_GB
    if res > 1:
        return f"{res:.2f}GB"

    res = f_n / _CONST_NUM_BYTES_IN_MB
    if res > 1:
        return f"{res:.2f}MB"

    res = f_n / _CONST_NUM_BYTES_IN_KB
    if res > 1:
        return f"{res:.2f}KB"

    return f"{num_bytes}B"


if __name__ == "__main__":
    try:
        assert len(sys.argv) >= 2, f"[Usage] python {sys.argv[0]} value"
        test_val = sys.argv[1]

        # usage example
        result = check_enough_disk(test_val)
        if result is not None:
            print(f"Enough disk space for <{test_val} Bytes>? [{result}]")

    except Exception as e:
        print(f"Error testing. Details: {e}")
