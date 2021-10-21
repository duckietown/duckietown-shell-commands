import os
import argparse

from dt_shell import DTCommandAbs, dtslogger, DTShell

MAP_EDITOR_LAUNCHER = "editor"

usage = """

## Basic usage

    Duckietown map editor for creating map (for new format).

        $ dts map editor [options]

"""
prog = "dts map editor"


class DTCommand(DTCommandAbs):
    help = "Duckietown Map Editor"

    @staticmethod
    def command(shell: DTShell, args):
        # print info
        dtslogger.info("Launching Duckietown Map Editor...")
        print("------>")
        # ---
        # run start-gui-tools
        parser = argparse.ArgumentParser(prog=prog, usage=usage)
        parser.add_argument("--image", default=None, help="Custom docker image of dt-gui-tools")
        parsed = parser.parse_args(args)
        flags = [
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
            "LOCAL",
        ]
        if parsed.image:
            flags.extend(["--image", parsed.image])
        shell.include.start_gui_tools.command(
            shell,
            flags,
        )
        # ---
        print("<------")
