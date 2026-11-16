import argparse

from dt_shell.commands import DTCommandConfigurationAbs


class DTCommandConfiguration(DTCommandConfigurationAbs):

    @classmethod
    def environment(cls, *args, **kwargs):
        return None

    @classmethod
    def parser(cls, *args, **kwargs):
        parser = argparse.ArgumentParser(prog="dts matrix capture", allow_abbrev=False)
        parser.add_argument("--version", help="Installed native Renderer version to capture.")
        parser.add_argument("--pid", type=int, help="Disambiguate running Renderers of that version.")
        parser.add_argument("--device", type=int, default=0, help="gpucapture device ID (local Mac: 0).")
        parser.add_argument("--boundary", type=int, help="Disambiguate capture boundaries; one frame is required.")
        parser.add_argument("--input", help="Analyse an existing .gputrace bundle instead of recording.")
        parser.add_argument("--output", help="New directory for the capture, analysis and fetched resources.")
        parser.add_argument("--check", action="store_true", help="Check host tools and storage without recording.")
        parser.add_argument(
            "--profile", action="store_true",
            help="Profile a new copy of --input after stopping the live workload; uses the default GPU policy.",
        )
        parser.add_argument(
            "--profile-execution", choices=("overlapping", "serial"),
            help="Replay scheduling for --profile (default: overlapping); not live workload throughput.",
        )
        parser.add_argument(
            "--browse", action="append", default=[], metavar="NODE",
            help="List all children of a navigable gpudebug tree path.",
        )
        parser.add_argument(
            "--inspect", action="append", default=[], metavar="NODE",
            help="Inspect a gpudebug tree path, such as /resources/render_pipelines/rps0.",
        )
        parser.add_argument(
            "--fetch", action="append", default=[], metavar="NODE",
            help="Export a buffer or shader-source node to the result directory.",
        )
        parser.add_argument("--verbose", action="store_true")
        return parser

    @classmethod
    def aliases(cls):
        return []
