from dt_shell import DTCommandAbs, DTShell
from utils.assets_utils import get_asset_icon_path
from utils.duckietown_viewer_utils import \
    ensure_duckietown_viewer_installed, launch_viewer, resolve_os_family

# NOTE: this must match the name of the launcher in the dt-duckietown-viewer project
LAUNCHER_NAME = "image_viewer"
ICON_ASSET = "icon-image-viewer.png"


class DTCommand(DTCommandAbs):
    help = "Runs the image viewer"

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = DTCommand._resolve_parsed(args, kwargs.get("parsed"))
        # ---
        # make sure the app is installed
        browser = parsed.browser
        os_family = resolve_os_family(parsed.os_family, browser)
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
            no_pull=parsed.no_pull,
            window_args={
                "height": 634,
                "icon": get_asset_icon_path(ICON_ASSET),
                "min-height": 634,
                "min-width": 694,
                "width": 694
            }
        )
