import os
import argparse
import subprocess

from utils.dtproject_utils import DTProject

from dt_shell import DTShell, DTCommandAbs, dtslogger


class DTCommand(DTCommandAbs):

    help = "Computes the diff between the current project and its template"

    # configure arguments
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-C",
        "--workdir",
        default=None,
        help="Directory containing the project to work on"
    )
    parser.add_argument(
        "-t",
        "--template",
        default=None,
        help="Template to use (default = project's template)"
    )
    parser.add_argument(
        "-v",
        "--version",
        default=None,
        type=str,
        help="Version of the template to use (default = project's template version)"
    )
    parser.add_argument(
        "--apply",
        default=False,
        action='store_true',
        help="Whether to apply the diff"
    )

    @staticmethod
    def command(shell: DTShell, args):
        parsed, _ = DTCommand.parser.parse_known_args(args=args)
        # ---
        # verify version
        if parsed.version is not None:
            try:
                _ = int(parsed.version)
            except ValueError:
                dtslogger.error('The argument -v/--version must be an integer.')
                return
        code_dir = parsed.workdir if parsed.workdir else os.getcwd()
        dtslogger.info('Project workspace: {}'.format(code_dir))
        # show info about project
        shell.include.devel.info.command(shell, args)
        # get info about current project
        project = DTProject(code_dir)
        # check if the index is clean
        if project.is_dirty():
            dtslogger.warning('Your index is not clean.')
            dtslogger.warning('This command compares the template against committed changes.')
            print()
        # get template and template version
        template = project.type
        if parsed.template is not None:
            template = parsed.template
        template_version = 'v' + project.type_version
        if parsed.version is not None:
            template_version = 'v'+parsed.version
        # script path
        script_path = os.path.join(
            os.path.abspath(os.path.dirname(__file__)), '..', 'assets', 'template_ops.sh'
        )
        # perform action
        env = {
            'CODE_DIR': code_dir,
            'TEMPLATE_TYPE': template,
            'TEMPLATE_VERSION': template_version,
            'APPLY_DIFF': str(int(parsed.apply))
        }
        p = subprocess.Popen(script_path, env=env, shell=True)
        p.communicate()

    @staticmethod
    def complete(shell, word, line):
        return []


def _run_cmd(cmd):
    print(cmd)
    return [l for l in subprocess.check_output(cmd).decode("utf-8").split("\n") if l]
