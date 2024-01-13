import argparse
import os
from types import SimpleNamespace
from typing import Optional

from dt_shell import DTCommandAbs, DTShell, UserError

from dtproject import DTProject
from utils.cli_utils import ask_confirmation
from utils.exceptions import UnpinnedDependenciesError


class DTCommand(DTCommandAbs):
    help = "Makes sure that a project can be sent to production"

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parser: argparse.ArgumentParser = DTCommand.parser
        # configure arguments
        parsed, _ = parser.parse_known_args(args=args)
        if "parsed" in kwargs:
            parsed.__dict__.update(kwargs["parsed"].__dict__)
        # ---
        parsed.workdir = os.path.abspath(parsed.workdir)
        project = DTProject(parsed.workdir)

        # make sure the project working directory is clean
        if not project.is_clean():
            raise UserError("This project has uncommitted changes. Please, commit before continuing.")

        # make sure python dependencies are pinned
        pip_resolve_check_args: SimpleNamespace = SimpleNamespace(check=True)
        try:
            shell.include.devel.pip.resolve.command(shell, [], parsed=pip_resolve_check_args)
        except UnpinnedDependenciesError as e:
            if not parsed.fix:
                raise e

        # make sure the git repository is tagged
        if project.head_version == "latest":
            # this is a nightly build, we need to tag the repo or bail
            if parsed.fix:
                answer = ask_confirmation(
                    f"This project repository's HEAD is not tagged. You need to assign a new tag before you "
                    f"can make a release out of this project. We can bump the current version for you and "
                    f"make a new version tag. What part do you want to bump?",
                    default="q",
                    choices={"q": "Quit", "|": "---------", "m": "Minor", "p": "Patch"},
                    question="Do you want to continue?",
                )
                part: Optional[str] = None
                if answer == "m":
                    # minor bump
                    part = "minor"
                elif answer == "p":
                    # patch bump
                    part = "patch"
                else:
                    pass
                # check part to bump
                if part is None:
                    raise UserError("This project repository's HEAD is not tagged. Release a new tag before "
                                    "continuing.")
                # bump
                bump_args: SimpleNamespace = SimpleNamespace(part=part)
                shell.include.devel.bump.command(shell, [], parsed=bump_args)
            else:
                raise UserError("This project repository's HEAD is not tagged. Release a new tag before "
                                "continuing.")

    @staticmethod
    def complete(shell, word, line):
        return []
