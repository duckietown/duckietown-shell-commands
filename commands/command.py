from __future__ import print_function

from dt_shell import DTCommandAbs
from dt_shell.commands_ import _get_commands


class DTCommand(DTCommandAbs):
    help = 'Shows the list of all the commands available in the shell.'
    args = ['--core', '--installed', '--installable']

    @staticmethod
    def command(shell, args):
        # get installed commands
        installed = set(shell.commands.keys()).difference(shell.core_commands)
        # get the commands that are available but not installed
        res = _get_commands(shell.commands_path, all_commands=True)
        all_commands = set(res.keys()) if res is not None else set()
        not_installed = all_commands.difference(set(shell.commands.keys()))
        # parse args
        filter_enabled = len(set(args).intersection(DTCommand.args)) > 0
        show_core = not filter_enabled or '--core' in args
        show_installed = not filter_enabled or '--installed' in args
        show_installable = not filter_enabled or '--installable' in args
        # show core commands
        if show_core:
            print("Core commands:")
            for cmd in shell.core_commands:
                print('\t%s' % cmd)
            # add new line if there is more to print
            if show_installed or show_installable: print('')
        # show installed commands
        if show_installed:
            print("Installed commands:")
            for cmd in installed:
                print('\t%s' % cmd)
            if len(installed) == 0: print('\t<empty>')
            # add new line if there is more to print
            if show_installable: print('')
        # show installable commands
        if show_installable:
            print("Installable commands:")
            for cmd in not_installed:
                print('\t%s' % cmd)
            if len(not_installed) == 0: print('\t<empty>')
        return True

    @staticmethod
    def complete(shell, word, line):
        return DTCommand.args
