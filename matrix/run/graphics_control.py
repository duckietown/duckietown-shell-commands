"""Private handoff from a native Renderer to its supervising launcher."""

from pathlib import Path

from dt_shell import dtslogger


GRAPHICS_RESTART_FILE = "DT_MATRIX_GRAPHICS_RESTART_FILE"
GRAPHICS_API_ENV = "DT_MATRIX_GRAPHICS_API"
GRAPHICS_RESTART_ERROR = "DT_MATRIX_GRAPHICS_RESTART_ERROR"
GRAPHICS_DB = "duckiematrix-renderer"
LINUX_API_FLAGS = {"auto": [], "vulkan": ["-force-vulkan"], "opengl": ["-force-glcore"]}
API_SWITCHES = {"-force-vulkan", "-force-opengl", "-force-glcore"}


def enabled(parsed, os_family: str) -> bool:
    return os_family == "linux" and not parsed.browser and not parsed.container_image


def with_api(command: list[str], graphics: str) -> list[str]:
    # These are Unity switches, not Renderer options: they must be set before the process starts.
    return [arg for arg in command if arg not in API_SWITCHES] + LINUX_API_FLAGS[graphics]


def consume_request(request: Path) -> str | None:
    try:
        with request.open(encoding="ascii") as stream:
            value = stream.read(16)
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError) as error:
        dtslogger.warning("Ignoring unreadable Renderer graphics request: %s", error)
        return None
    try:
        request.unlink()
    except OSError as error:
        dtslogger.warning("Could not clear the Renderer graphics request: %s", error)
        return None
    if value not in LINUX_API_FLAGS:
        dtslogger.warning("Ignoring invalid Renderer graphics API request.")
        return None
    return value
