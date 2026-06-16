from dt_shell import DTCommandAbs, DTShell

from utils.duckietown_viewer_utils import (
    ensure_duckietown_viewer_installed,
    launch_viewer,
    resolve_os_family,
)


class DTCommand(DTCommandAbs):
    help = "Launches a Duckietown Viewer frontend window"

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = DTCommand._resolve_parsed(args, kwargs.get("parsed"))
        os_family = resolve_os_family(parsed.os_family, False)
        ensure_duckietown_viewer_installed(os_family)

        window_args = {}
        for entry in parsed.window_arg:
            if "=" not in entry:
                raise ValueError(
                    f"Invalid --window-arg value {entry!r}; expected KEY=VALUE."
                )
            key, value = entry.split("=", 1)
            if not key:
                raise ValueError(
                    f"Invalid --window-arg value {entry!r}; key cannot be empty."
                )
            window_args[key] = value

        launch_viewer(
            parsed.app,
            os_family=os_family,
            robot=None,
            verbose=False,
            fullscreen=parsed.fullscreen,
            menu=parsed.menu,
            on_top=parsed.on_top,
            enable_hardware_acceleration=parsed.enable_hardware_acceleration,
            browser=False,
            no_pull=False,
            window_args=window_args,
        )