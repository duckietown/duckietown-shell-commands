import argparse
import dataclasses
import json
import os

import termcolor

from dt_shell import DTCommandAbs, dtslogger, UserError
from dt_shell.env_checks import get_dockerhub_username, check_docker_environment
from duckietown_challenges import get_duckietown_server_url
from duckietown_challenges.cmd_submit_build import submission_build
from duckietown_challenges.rest import ServerIsDown
from duckietown_challenges.rest_methods import get_registry_info, dtserver_submit2, dtserver_get_compatible_challenges
from duckietown_challenges.submission_read import read_submission_info


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        check_docker_environment()

        token = shell.get_dt1_token()

        prog = 'dts challenges submit'
        usage = """
        

Submission:

    %(prog)s --challenge NAME



## Building options

Rebuilds ignoring Docker cache

    %(prog)s --no-cache



## Attaching user data
    
Submission with an identifying label:

    %(prog)s --user-label  "My submission"    
    
Submission with an arbitrary JSON payload:

    %(prog)s --user-meta  '{"param1": 123}'   
        

        
        
"""
        parser = argparse.ArgumentParser(prog=prog, usage=usage)

        group = parser.add_argument_group("Submission identification")
        parser.add_argument('--challenge',
                            help="Specify challenge name.", default=None)
        group.add_argument('--user-label', dest='message', default=None, type=str,
                           help="Submission message")
        group.add_argument('--user-meta', dest='metadata', default=None, type=str,
                           help="Custom JSON structure to attach to the submission")

        group = parser.add_argument_group("Building settings.")

        group.add_argument('--no-cache', dest='no_cache', action='store_true', default=False)
        group.add_argument('--impersonate', type=int, default=None)

        group.add_argument('-C', dest='cwd', default=None, help='Base directory')

        parsed = parser.parse_args(args)
        impersonate = parsed.impersonate
        if parsed.cwd is not None:
            dtslogger.info('Changing to directory %s' % parsed.cwd)
            os.chdir(parsed.cwd)

        if not os.path.exists('submission.yaml'):
            msg = 'Expected a submission.yaml file in %s.' % (os.path.realpath(os.getcwd()))
            raise UserError(msg)

        sub_info = read_submission_info('.')

        try:
            ri = get_registry_info(token=token, impersonate=impersonate)

            registry = ri.registry

            compat = dtserver_get_compatible_challenges(token=token, impersonate=impersonate,
                                                        submission_protocols=sub_info.protocols)
            if not compat.compatible:
                msg = 'There are no compatible challenges with protocols %s.' % sub_info.protocols
                raise UserError(msg)

            if parsed.message:
                sub_info.user_label = parsed.message
            if parsed.metadata:
                sub_info.user_metadata = json.loads(parsed.metadata)
            if parsed.challenge:
                sub_info.challenge_names = parsed.challenge.split(',')
            if sub_info.challenge_names is None:
                sub_info.challenge_names = compat.compatible

            print('I will submit to the challenges %s' % sub_info.challenge_names)

            for c in sub_info.challenge_names:
                if not c in compat.available_submit:
                    msg = 'The challenge "%s" does not exist among %s.' % (c, list(compat.available_submit))
                    raise UserError(msg)
                if not c in compat.compatible:
                    msg = 'The challenge "%s" is not compatible with protocols %s .' % (c, sub_info.protocols)
                    raise UserError(msg)
            username = get_dockerhub_username(shell)


            print('')
            print('')
            br = submission_build(username=username, registry=registry,
                                  no_cache=parsed.no_cache)

            data = {'image': dataclasses.asdict(br),
                    'user_label': sub_info.user_label,
                    'user_payload': sub_info.user_metadata,
                    'protocols': sub_info.protocols}

            data = dtserver_submit2(token=token,
                                    challenges=sub_info.challenge_names, data=data,
                                    impersonate=impersonate)

            # print('obtained:\n%s' % json.dumps(data, indent=2))
            component_id = data['component_id']
            submissions = data['submissions']
            url_component = href(get_duckietown_server_url() + '/humans/components/%s' % component_id)

            msg = f'''
    
    Successfully created component {component_id}.
    
    {url_component}
    
    
    This component has been entered in {len(submissions)} challenge(s).
            '''

            for challenge_name, sub_info in submissions.items():
                submission_id = sub_info['submission_id']
                url_submission = href(get_duckietown_server_url() + '/humans/submissions/%s' % submission_id)
                challenge_title = sub_info['challenge']['title']
                submission_id_color = termcolor.colored(submission_id, 'cyan')
                P = dark('$')
                head = bright(f'## Challenge {challenge_name} - {challenge_title}')
                msg += '\n\n' + f'''
                
    {head}
    
    You can track the progress at:
    
        {url_submission}
             
    You can follow its fate using:
    
        {P} dts challenges follow --submission {submission_id_color}
        
    You can speed up the evaluation using your own evaluator:
    
        {P} dts challenges evaluator --submission {submission_id_color}
        
    '''.strip()
                manual = href('http://docs.duckietown.org/DT19/AIDO/out/')
                msg += f'''
    
    For more information, see the manual at {manual}
    '''

            shell.sprint(msg)
        except ServerIsDown as e:
            msg = 'The server is temporarily down. Please try again later.'
            msg +='\n\n' + str(e)
            raise UserError(msg)


def bright(x):
    return termcolor.colored(x, 'blue')


def dark(x):
    return termcolor.colored(x, attrs=['dark'])


def href(x):
    return termcolor.colored(x, 'blue', attrs=['underline'])

# class CouldNotReadInfo(Exception):
#     pass

#
# @dataclass
# class SubmissionInfo:
#     challenges: Optional[List[str]]
#     user_label: Optional[str]
#     user_payload: Optional[dict]
#     protocols: List[str]
#
#
# def read_submission_info(dirname) -> SubmissionInfo:
#     bn = 'submission.yaml'
#     fn = os.path.join(dirname, bn)
#
#     try:
#         data = read_yaml_file(fn)
#     except BaseException:
#         raise CouldNotReadInfo(traceback.format_exc())
#     try:
#         known = ['challenge', 'protocol', 'user-label', 'user-payload', 'description']
#         challenges = data.pop('challenge', None)
#         if isinstance(challenges, str):
#             challenges = [challenges]
#         protocols = data.pop('protocol')
#         if not isinstance(protocols, list):
#             protocols = [protocols]
#         user_label = data.pop('user-label', None)
#         user_payload = data.pop('user-payload', None)
#         description = data.pop('description', None)
#         if data:
#             msg = 'Unknown keys: %s' % list(data)
#             msg += '\n\nI expect only the keys %s' % known
#             raise Exception(msg)
#         return SubmissionInfo(challenges, user_label, user_payload, protocols)
#     except BaseException as e:
#         msg = 'Could not read file %r: %s' % (fn, traceback.format_exc())
#         raise CouldNotReadInfo(msg)

#
# def read_yaml_file(fn):
#     if not os.path.exists(fn):
#         msg = 'File does not exist: %s' % fn
#         raise Exception(msg)
#
#     with open(fn) as f:
#         data = f.read()
#
#         try:
#             return yaml.load(data, Loader=yaml.Loader)
#         except Exception as e:
#             msg = 'Could not read YAML file %s:\n\n%s' % (fn, e)
#             raise Exception(msg)
