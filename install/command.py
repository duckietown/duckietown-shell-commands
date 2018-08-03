from __future__ import print_function
from dt_shell import DTCommandAbs

class DTCommand(DTCommandAbs):

    help = 'Installs a new command.'

    @staticmethod
    def command(shell, args):
        # get installed commands
        installed = set(shell.commands.keys())
        # get the commands that are available but not installed
        res = shell._get_commands(shell.commands_path, all=True)
        all_commands = set(res.keys()) if res is not None else set()
        not_installed = all_commands.difference(installed)
        # get list of commands to install / already-installed / not-installable
        requested_to_install = set(args)
        not_installable = requested_to_install.difference(all_commands)
        already_installed = requested_to_install.intersection(installed)
        to_install = requested_to_install.intersection(all_commands).difference(installed)
        need_reload = False
        # already installed
        for cmd in already_installed:
            print( 'The command `%s` is already installed.' % cmd )
        # not installable
        for cmd in not_installable:
            print( 'The command `%s` cannot be found.' % cmd )
        # install
        for cmd in to_install:
            print( 'Installing command `%s`...' % cmd, end='' )
            shell.enable_command(cmd)
            need_reload = True
            print( 'Done!' )
        # update list of commands
        if need_reload:
            print( 'Updating index...', end='' )
            shell.reload_commands()
            print( 'Done!' )
        else: print( 'Nothing to do.' )
        return True

    @staticmethod
    def complete(shell, word, line):
        # get installed commands
        installed = set(shell.commands.keys())
        # get the commands that are available but not installed
        res = shell._get_commands(shell.commands_path, all=True)
        all_commands = set(res.keys()) if res is not None else set()
        not_installed = all_commands.difference(installed)
        # remove the core commands
        installable = not_installed.difference( shell.core_commands )
        # return not installed commands
        return list(installable)
