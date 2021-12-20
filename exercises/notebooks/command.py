from dt_shell import DTCommandAbs, DTShell

usage = """

## Basic usage
    This is a helper for the exercises. 
    You must run this command inside an exercise folder. 

    To know more on the `exercises` commands, use `dts exercises -h`.

        $ dts exercises notebooks 

"""


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        # this is just a proxy command to `dts exercises lab`
        shell.include.exercises.lab.command(shell, args)
