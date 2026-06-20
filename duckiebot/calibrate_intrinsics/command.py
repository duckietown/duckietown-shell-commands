from dt_shell import DTCommandAbs, DTShell
from utils.assets_utils import get_asset_icon_path
from utils.duckietown_viewer_utils import \
    ensure_duckietown_viewer_installed, launch_viewer, resolve_os_family, should_delegate_viewer_frontend

# NOTE: this must match the name of the launcher in the dt-duckietown-viewer project
LAUNCHER_NAME = "intrinsics_calibrator"
ICON_ASSET = "icon-calibrate-intrinsics.png"


class DTCommand(DTCommandAbs):
    help = "Runs the intrinsics calibrator"

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = DTCommand._resolve_parsed(args, kwargs.get("parsed"))
        # ---
        # make sure the app is installed
        browser = parsed.browser
        local = parsed.local
        delegate_frontend = should_delegate_viewer_frontend(browser, local)
        os_family = resolve_os_family(parsed.os_family, browser)
        if not delegate_frontend:
            ensure_duckietown_viewer_installed(os_family)
        # launch viewer
        launch_viewer(
            LAUNCHER_NAME,
            os_family=os_family,
            robot=parsed.robot,
            verbose=parsed.verbose,
            fullscreen=parsed.fullscreen,
            on_top=parsed.on_top,
            enable_hardware_acceleration=parsed.enable_hardware_acceleration,
            browser=browser,
            local=local,
            no_pull=parsed.no_pull,
            window_args={
                "height": 634,
                "icon": get_asset_icon_path(ICON_ASSET),
                "min-height": 634,
                "min-width": 814,
                "width": 814
            }
        )
