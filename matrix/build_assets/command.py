import argparse

from dt_shell import DTCommandAbs, DTShell


class DTCommand(DTCommandAbs):

    help = f'Builds map\'s assets'

    @staticmethod
    def _parse_args(args):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-m",
            "--map",
            required=True,
            type=str,
            help="Directory containing the map to build the assets for"
        )
        parser.add_argument(
            "-vv",
            "--verbose",
            default=False,
            action="store_true",
            help="Run in verbose mode"
        )
        parsed, _ = parser.parse_known_args(args=args)
        return parsed

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = kwargs.get("parsed", None)
        if parsed is None:
            parsed = DTCommand._parse_args(args)
        # ---
        setattr(parsed, "build_assets", True)
        engine = shell.include.matrix.engine.run.make_engine(shell, parsed, use_defaults=True)
        if engine is None:
            return
        # ---
        engine.start()
        engine.join()

    @staticmethod
    def complete(shell, word, line):
        return []
