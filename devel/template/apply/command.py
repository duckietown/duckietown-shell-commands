from dt_shell import DTCommandAbs, DTShell


class DTCommand(DTCommandAbs):

    help = "Re-applies a template to the project"

    @staticmethod
    def command(shell: DTShell, args):
        # call diff
        shell.include.devel.template.diff.command(shell, args + ["--apply"])

    @staticmethod
    def complete(shell, word, line):
        # call diff
        shell.include.devel.template.diff.complete(shell, word, line)
