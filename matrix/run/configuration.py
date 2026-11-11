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
            "--renderer-binary",
            default=None,
            type=str,
            help="Path to a local renderer binary",
        )
        parser.add_argument(
            "-S",
            "--standalone",
            default=False,
            action="store_true",
            help="Run both engine and renderer",
        )
        parser.add_argument(
            "--gym",
            "--simulation",
            dest="simulation",
            default=False,
            action="store_true",
            help="Run the standalone engine in simulation mode",
        )
        parser.add_argument(
            "-t",
            "-dt",
            "--delta-t",
            default=None,
            type=float,
            help="Time step (requires --gym/--simulation)",
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
            "--environments",
            default=1,
            type=int,
            help="Number of co-located environments (requires --standalone)",
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
            "--on-top",
            default=False,
            action="store_true",
            help="Always stay on top of other windows",
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
            help="Print profiling tables on exit (requires -S/--standalone)",
        )
        parser.add_argument(
            "--live-profiler",
            default=False,
            action="store_true",
            help="Continuously update profiling tables (requires -S/--standalone)",
        )
        parser.add_argument(
            "--trace",
            default=False,
            action="store_true",
            help="Record the native macOS Renderer with Instruments Metal System Trace",
        )
        parser.add_argument(
            "--trace-export",
            default=False,
            action="store_true",
            help="Export selected CPU/Metal XML tables beside the recording (requires --trace)",
        )
        parser.add_argument(
            "--trace-template",
            default=None,
            metavar="PATH.tracetemplate",
            help="Use a saved Instruments template containing Metal Application and Time Profiler (requires --trace)",
        )
        parser.add_argument(
            "--trace-performance-state",
            choices=("default", "minimum", "medium", "maximum"),
            default=None,
            help=(
                "Verify the template and recording use this GPU performance selector; "
                "non-default states require --trace-template saved with that state "
                "(requires --trace; does not guarantee fixed hardware clocks)"
            ),
        )
        for option, description in (
            ("--trace-waiting-threads", "Record waiting-thread call stacks"),
            ("--trace-kernel-callstacks", "Record kernel call stacks"),
            ("--trace-context-switch-sampling", "Sample context switches"),
        ):
            parser.add_argument(
                option,
                default=False,
                action="store_true",
                help=f"{description} (requires --trace and Xcode recording-options support)",
            )
        parser.add_argument(
            "--trace-start-session",
            default=None,
            type=int,
            metavar="SESSION",
            help=(
                "Wait for Renderer session 1-1000000 before recording "
                "(requires --trace --live-profiler; default: record at launch)"
            ),
        )
        parser.add_argument(
            "--trace-duration",
            default=30,
            type=int,
            metavar="SECONDS",
            help=(
                "Request a stop after 1-300 seconds, or -1 until the Renderer exits "
                "(default: 30; Instruments setup/shutdown can extend the run envelope)"
            ),
        )
        parser.add_argument(
            "--trace-window",
            default=None,
            type=int,
            metavar="SECONDS",
            help=(
                "Retain only the last 1-60 seconds, or -1 for the entire recording; "
                "this does not stop recording (default: 10, or the duration if shorter; "
                "an equal-duration window retains the whole capture without rolling)"
            ),
        )
        parser.add_argument(
            "--trace-output",
            default=None,
            type=str,
            metavar="PATH.trace",
            help=(
                "Save --trace to this path on the calling machine "
                "(default: ~/.duckietown/duckiematrix/traces/<unique-name>.trace)"
            ),
        )
        parser.add_argument(
            "--container-image",
            default=None,
            type=str,
            help="Run the renderer binary in the given container image",
        )
        parser.add_argument(
            "--target-frame-rate",
            default=None,
            type=int,
            help="Target renderer frame rate",
        )
        parser.add_argument(
            "--cameras-only",
            default=False,
            action="store_true",
            help="Render sensor cameras without the spectator's 3D world view",
        )
        parser.add_argument(
            "--shm-path",
            default=None,
            type=str,
            help=(
                "DTPS shared-memory base path for standalone gym mode, in a "
                "private directory owned by the current user with permissions 0700"
            ),
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
            "--local",
            default=False,
            action="store_true",
            help="Run the native renderer locally instead of delegating it to the host",
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
