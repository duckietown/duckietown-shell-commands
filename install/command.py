from dt_shell import DTCommandAbs, DTShell, dtslogger
from dt_shell.commands_ import _get_commands


class DTCommand(DTCommandAbs):
    help = "Installs a new command."

    @staticmethod
    def command(shell: DTShell, args):
        # get installed commands
        installed = set(shell.commands.keys())
        # get the commands that are available but not installed
        res = _get_commands(shell.commands_path, all_commands=True)
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
            dtslogger.info("The command `%s` is already installed." % cmd)
        # not installable
        for cmd in not_installable:
            dtslogger.info("The command `%s` cannot be found." % cmd)
        # install
        for cmd in to_install:
            dtslogger.info("Installing command `%s`..." % cmd)
            shell.enable_command(cmd)
            need_reload = True
            dtslogger.info("Done!")
        # update list of commands
        if need_reload:
            dtslogger.info("Updating index...")
            shell.reload_commands()
            dtslogger.info("Done!")
        else:
            dtslogger.info("Nothing to do.")
        return True

    @staticmethod
    def complete(shell, word, line):
        # get installed commands
        installed = set(shell.commands.keys())
        # get the commands that are available but not installed
        res = shell._get_commands(shell.commands_path, all_commands=True)
        all_commands = set(res.keys()) if res is not None else set()
        not_installed = all_commands.difference(installed)
        # remove the core commands
        installable = not_installed.difference(shell.core_commands)
        # return not installed commands
        return list(installable)
