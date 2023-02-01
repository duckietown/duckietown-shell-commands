import argparse
import os
from types import SimpleNamespace

from dt_shell import DTCommandAbs, dtslogger, DTShell, UserError
from utils.dtproject_utils import DTProject
from utils.misc_utils import get_user_login


class DTCommand(DTCommandAbs):
    help = "Builds a Duckietown project into an image"

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        print(
            'You called the "%s" command, level %d, with arguments %r' % (
                DTCommand.name,
                DTCommand.level,
                args
            )
        )

    @staticmethod
    def complete(shell, word, line):
        return []
