from dt_shell import DTCommandAbs

class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        print 'TODO: This is `%s`, and I received the arguments `%r`' % (DTCommand.name, args)
