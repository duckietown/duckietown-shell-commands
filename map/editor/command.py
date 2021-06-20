import os

from dt_shell import DTCommandAbs, dtslogger, DTShell

MAP_EDITOR_LAUNCHER = "editor"


class DTCommand(DTCommandAbs):

    help = "Duckietown Map Editor"

    @staticmethod
    def command(shell: DTShell, args):
        # print info
        dtslogger.info("Launching Duckietown Map Editor...")
        print("------>")
        # ---
        # run start-gui-tools
        shell.include.start_gui_tools.command(
            shell,
            [
                "--launcher",
                MAP_EDITOR_LAUNCHER,
                "--mount",
                f"{os.getcwd()}:/out",
                "--wkdir",
                f"/out",
                "--uid",
                str(os.getuid()),
                "--name",
                "map-editor",
                "--no-scream",
                "LOCAL"
            ],
        )
        # ---
        print("<------")
