import os
import argparse
import subprocess
from dt_shell import DTShell, DTCommandAbs, dtslogger


class DTCommand(DTCommandAbs):
    help = "Computes the diff between the current project and its template"

    @staticmethod
    def command(shell: DTShell, args):
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
            type=int,
            choices=range(0, 99),
            help="Version of the template to use (default = project's template version)"
        )
        parser.add_argument(
            "--apply",
            default=False,
            action='store_true',
            help="Whether to apply the diff"
        )
        parsed, _ = parser.parse_known_args(args=args)
        # ---
        code_dir = parsed.workdir if parsed.workdir else os.getcwd()
        dtslogger.info('Project workspace: {}'.format(code_dir))
        # show info about project
        shell.include.devel.info.command(shell, args)
        # get info about current project
        project_info = shell.include.devel.info.get_project_info(code_dir)
        # get info about current repo
        repo_info = shell.include.devel.info.get_repo_info(code_dir)
        # check if the index is clean
        nmodified = repo_info['INDEX_NUM_MODIFIED']
        nadded = repo_info['INDEX_NUM_ADDED']
        # check if the index is clean
        if nmodified + nadded > 0:
            dtslogger.warning('Your index is not clean.')
            dtslogger.warning('This command compares the template against committed changes.')
            print()
        # get template and template version
        template = project_info['TYPE']
        if parsed.template is not None:
            template = parsed.template
        template_version = 'v'+project_info['TYPE_VERSION']
        if parsed.version is not None:
            template_version = parsed.version
        # script path
        script_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'assets', 'template_ops.sh')
        # perform action
        vars = {
            'CODE_DIR': code_dir,
            'TEMPLATE_TYPE': template,
            'TEMPLATE_VERSION': template_version,
            'APPLY_DIFF': "{}".format(int(parsed.apply))
        }
        p = subprocess.Popen(script_path, env=vars, shell=True)
        p.communicate()

    @staticmethod
    def complete(shell, word, line):
        return []


def _run_cmd(cmd):
    print(cmd)
    return [l for l in subprocess.check_output(cmd).decode("utf-8").split("\n") if l]
