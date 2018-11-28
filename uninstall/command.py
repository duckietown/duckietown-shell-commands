from __future__ import print_function

from dt_shell import DTCommandAbs, dtslogger


class DTCommand(DTCommandAbs):
    help = 'Uninstalls a command.'

    @staticmethod
    def command(shell, args):
        # get installed commands
        installed = set(shell.commands.keys())
        # get list of commands to uninstall / not-uninstallable
        requested_to_uninstall = set(args)
        to_uninstall = requested_to_uninstall.intersection(installed)
        not_uninstallable = requested_to_uninstall.difference(installed)
        need_reload = False
        # not uninstallable
        for cmd in not_uninstallable:
            dtslogger.warn('The command `%s` cannot be found.' % cmd)
        # uninstall
        for cmd in to_uninstall:
            dtslogger.info('Removing command `%s`...' % cmd, end='')
            shell.disable_command(cmd)
            need_reload = True
            dtslogger.info('Successfully completed calibration!')
            print('Done!')
        # update list of commands
        if need_reload:
            print('Updating index...', end='')
            shell.reload_commands()
            print('Done!')
        else:
            print('Nothing to do.')
        return True

    @staticmethod
    def complete(shell, word, line):
        # get installed commands
        installed = set(shell.commands.keys())
        # remove the core commands
        uninstallable = installed.difference(shell.core_commands)
        # return uninstallable commands
        return uninstallable
