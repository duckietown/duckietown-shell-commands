from dt_shell import DTCommandAbs, DTShell

usage = """

## Basic usage
    This is a helper for the oakd. 
    You must run this command inside an exercise folder. 

    To know more on the `oakd` commands, use `dts oakd -h`.

        $ dts oakd notebooks 

"""


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell: DTShell, args):
        # this is just a proxy command to `dts oakd lab`
        shell.include.oakd.lab.command(shell, args)
