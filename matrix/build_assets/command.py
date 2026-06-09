from dt_shell import DTCommandAbs, DTShell


class DTCommand(DTCommandAbs):

    help = f'Builds map\'s assets'

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = DTCommand._resolve_parsed(args, kwargs.get("parsed"))
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
