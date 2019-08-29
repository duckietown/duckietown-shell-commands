import os
import argparse
import subprocess
from termcolor import colored
from dt_shell import DTCommandAbs

PROJECT_INFO = """
{project}
{space}{name}
{space}Version: {VERSION}
{space}Path: {PATH}
{space}Type: {TYPE}
{space}Template Version: {TYPE_VERSION}
{end}
"""

class DTCommand(DTCommandAbs):

    help = 'Shows information about the current project'

    REQUIRED_METADATA_KEYS = {
        '*': [
            'TYPE_VERSION'
        ],
        '1': [
            'TYPE',
            'VERSION'
        ]
    }

    @staticmethod
    def command(shell, args):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument('-C', '--workdir', default=None,
                            help="Directory containing the project to show")
        parsed, _ = parser.parse_known_args(args=args)
        # ---
        code_dir = parsed.workdir if parsed.workdir else os.getcwd()
        info = DTCommand.get_project_info(code_dir)
        info.update({
            'name': colored('Name: '+info['NAME'], 'grey', 'on_white'),
            'project': colored('Project:', 'grey', 'on_white'),
            'space': colored('  ', 'grey', 'on_white'),
            'end': colored('________', 'grey', 'on_white')
        })
        print(PROJECT_INFO.format(**info))


    @staticmethod
    def complete(shell, word, line):
        return []


    @staticmethod
    def get_project_info(path):
        apath = os.path.abspath(path)
        project_name = os.path.basename(apath)
        metafile = os.path.join(apath, '.dtproject')
        # if the file '.dtproject' is missing
        if not os.path.exists(metafile):
            msg = "The path '%s' does not appear to be a Duckietown project. " % (metafile)
            msg += "The metadata file '.dtproject' is missing."
            raise ValueError(msg)
        # load '.dtproject'
        metadata = []
        with open(metafile, 'rt') as metastream:
            metadata = metastream.readlines()
        # empty metadata?
        if not metadata:
            msg = "The metadata file '.dtproject' is empty."
            raise SyntaxError(msg)
        # parse metadata
        metadata = {
            p[0].strip().upper(): p[1].strip() for p in [l.split('=') for l in metadata]
        }
        # look for version-agnostic keys
        for key in DTCommand.REQUIRED_METADATA_KEYS['*']:
            if key not in metadata:
                msg = "The metadata file '.dtproject' does not contain the key '%s'." % key
                raise SyntaxError(msg)
        # validate version
        VERSION = metadata['TYPE_VERSION']
        if VERSION == '*' or VERSION not in DTCommand.REQUIRED_METADATA_KEYS:
            msg = "The project version %s is not supported." % VERSION
            raise NotImplementedError(msg)
        # validate metadata
        for key in DTCommand.REQUIRED_METADATA_KEYS[VERSION]:
            if key not in metadata:
                msg = "The metadata file '.dtproject' does not contain the key '%s'." % key
                raise SyntaxError(msg)
        # metadata is valid
        metadata['NAME'] = project_name
        metadata['PATH'] = apath
        return metadata


    @staticmethod
    def get_repo_info(path):
        branch = _run_cmd(['git', '-C', path, 'rev-parse', '--abbrev-ref', 'HEAD'])[0]
        origin_url = _run_cmd(['git', '-C', path, 'config', '--get', 'remote.origin.url'])[0]
        if origin_url.endswith('.git'):
            origin_url = origin_url[:-4]
        repo = origin_url.split('/')[-1]
        # get info about current git INDEX
        nmodified = len(_run_cmd(['git', '-C', path, 'status', '--porcelain', '--untracked-files=no']))
        nadded = len(_run_cmd(['git', '-C', path, 'status', '--porcelain']))
        # return info
        return {
            'REPOSITORY': repo,
            'BRANCH': branch,
            'ORIGIN.URL': origin_url,
            'INDEX_NUM_MODIFIED': nmodified,
            'INDEX_NUM_ADDED': nadded
        }


def _run_cmd(cmd):
    return [l for l in subprocess.check_output(cmd).decode('utf-8').split('\n') if l]
