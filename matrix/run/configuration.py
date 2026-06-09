import argparse
from typing import Optional, List

from dt_shell.commands import DTCommandConfigurationAbs
from dt_shell.environments import ShellCommandEnvironmentAbs


class DTCommandConfiguration(DTCommandConfigurationAbs):

    @classmethod
    def environment(cls, *args, **kwargs) -> Optional[ShellCommandEnvironmentAbs]:
        """
        The environment in which this command will run.
        """
        return None

    @classmethod
    def parser(cls, *args, **kwargs) -> Optional[argparse.ArgumentParser]:
        """
        The parser this command will use.
        """
        parser = argparse.ArgumentParser(prog="dts matrix run")
        parser.add_argument(
            "-v",
            "--version",
            default=None,
            type=str,
            help="Run a specific version",
        )
        parser.add_argument(
            "-S",
            "--standalone",
            default=False,
            action="store_true",
            help="Run both engine and renderer",
        )
        parser.add_argument(
            "--engine-name",
            default=None,
            type=str,
            help="Name for the engine Docker container (default: dts-matrix-engine)"
        )
        parser.add_argument(
            "-m",
            "--map",
            default=None,
            type=str,
            help="Directory containing the map to load",
        )
        parser.add_argument(
            "--embedded",
            default=False,
            action="store_true",
            help="Use the embedded map directory as the root directory for '--map'",
        )
        parser.add_argument(
            "-e",
            "--engine",
            dest="engine_hostname",
            default=None,
            type=str,
            help="Hostname or IP address of the engine to connect to",
        )
        parser.add_argument(
            "-ep",
            "--engine-control-port",
            default=None,
            type=int,
            help="Control port of the engine to connect to (default: 7502)"
        )
        parser.add_argument(
            "-ewp",
            "--engine-ws-control-port",
            default=None,
            type=int,
            help="WebSocket control port of the engine to connect to (default: 7503, WebGL only)"
        )
        parser.add_argument(
            "--port-offset",
            default=0,
            type=int,
            help="Port offset applied to the engine (sets -ep and -ewp automatically)"
        )
        parser.add_argument(
            "-r",
            "--renderer-id",
            default=None,
            type=int,
            help="(Advanced) Use a specific `renderer_id`",
        )
        parser.add_argument(
            "-k",
            "--renderer-key",
            default=None,
            type=str,
            help="(Advanced) Authenticate the renderer using a key",
        )
        parser.add_argument(
            "-s",
            "--sandbox",
            default=False,
            action="store_true",
            help="Run in a sandbox map",
        )
        parser.add_argument(
            "-vk",
            "--force-vulkan",
            default=False,
            action="store_true",
            help="(Advanced) Force the use of the Vulkan rendering API",
        )
        parser.add_argument(
            "-gl",
            "--force-opengl",
            default=False,
            action="store_true",
            help="(Advanced) Force the use of the OpenGL rendering API",
        )
        parser.add_argument(
            "--link",
            dest="links",
            nargs=2,
            action="append",
            default=[],
            metavar=("matrix", "world"),
            help="Link robots inside the matrix to robots outside",
        )
        parser.add_argument(
            "--no-pull",
            default=False,
            action="store_true",
            help="Do not attempt to update the engine container image",
        )
        parser.add_argument(
            "--expose-ports",
            default=False,
            action="store_true",
            help="Expose all the ports with the host",
        )
        parser.add_argument(
            "--static-ports",
            default=False,
            action="store_true",
            help="Assign default values to all the ports",
        )
        parser.add_argument(
            "-vv",
            "--verbose",
            default=False,
            action="store_true",
            help="Run in verbose mode",
        )
        parser.add_argument(
            "--no-tutorial",
            default=False,
            action="store_true",
            help="Disable showing the tutorial",
        )
        parser.add_argument(
            "--profiler",
            default=False,
            action="store_true",
            help="Enable the profiler (requires -S/--standalone)",
        )
        parser.add_argument(
            "-os",
            "--os-family",
            default=None,
            type=str,
            help="Run for a given os-family",
        )
        parser.add_argument(
            "--browser",
            default=False,
            action="store_true",
            help="Run in browser mode",
        )
        parser.add_argument(
            "--xvfb",
            default=False,
            action="store_true",
            help="Run the native renderer under xvfb-run (Linux only)",
        )
        parser.add_argument(
            "--xvfb-args",
            default='-s "-screen 0 1920x1080x24"',
            type=str,
            help="Additional arguments passed to xvfb-run (use -s to set Xvfb server args)",
        )
        parser.add_argument(
            "--host",
            default="localhost",
            type=str,
            help="Hostname or IP address to bind the HTTP server",
        )
        parser.add_argument(
            "--port",
            default=None,
            type=int,
            help="Port number to bind the HTTP server",
        )
        return parser

    @classmethod
    def aliases(cls) -> List[str]:
        """
        Alternative names for this command.
        """
        return []
