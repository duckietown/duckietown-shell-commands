import argparse
import dataclasses
import json
import os

import termcolor

from challenges.challenges_cmd_utils import check_duckietown_challenges_version, wrap_server_operations
from dt_shell import DTCommandAbs, DTShell, dtslogger, UserError
from dt_shell.env_checks import check_docker_environment, get_dockerhub_username


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        check_duckietown_challenges_version()

        check_docker_environment()

        token = shell.get_dt1_token()

        prog = "dts challenges submit"
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
        parser.add_argument("--challenge", help="Specify challenge name.", default=None)
        group.add_argument(
            "--user-label", dest="message", default=None, type=str, help="Submission message",
        )
        group.add_argument(
            "--user-meta",
            dest="metadata",
            default=None,
            type=str,
            help="Custom JSON structure to attach to the submission",
        )

        group = parser.add_argument_group("Building settings.")

        group.add_argument("--no-cache", dest="no_cache", action="store_true", default=False)
        group.add_argument("--impersonate", type=int, default=None)

        group.add_argument(
            "--retire-same-label",
            action="store_true",
            default=False,
            help="Retire my submissions with the same label.",
        )

        group.add_argument("-C", dest="cwd", default=None, help="Base directory")

        parsed = parser.parse_args(args)
        impersonate = parsed.impersonate
        if parsed.cwd is not None:
            dtslogger.info("Changing to directory %s" % parsed.cwd)
            os.chdir(parsed.cwd)

        if not os.path.exists("submission.yaml"):
            msg = "Expected a submission.yaml file in %s." % (os.path.realpath(os.getcwd()))
            raise UserError(msg)

        from duckietown_challenges import get_duckietown_server_url
        from duckietown_challenges.cmd_submit_build import submission_build
        from duckietown_challenges.rest_methods import (
            dtserver_get_compatible_challenges,
            dtserver_retire_same_label,
            dtserver_submit2,
            get_registry_info,
        )
        from duckietown_challenges.submission_read import read_submission_info

        sub_info = read_submission_info(".")

        with wrap_server_operations():
            ri = get_registry_info(token=token, impersonate=impersonate)

            registry = ri.registry

            compat = dtserver_get_compatible_challenges(
                token=token, impersonate=impersonate, submission_protocols=sub_info.protocols,
            )
            if not compat.compatible:
                msg = (
                    "There are no compatible challenges with protocols %s,\n"
                    " or you might not have the necessary permissions." % sub_info.protocols
                )
                raise UserError(msg)

            if parsed.message:
                sub_info.user_label = parsed.message
            if parsed.metadata:
                sub_info.user_metadata = json.loads(parsed.metadata)
            if parsed.challenge:
                sub_info.challenge_names = parsed.challenge.split(",")
            if sub_info.challenge_names is None:
                msg = "You did not specify a challenge. I will use the first compatible one."
                print(msg)
                sub_info.challenge_names = [list(compat.compatible)[0]]

            if sub_info.challenge_names == ["all"]:
                sub_info.challenge_names = compat.compatible

            print("I will submit to the challenges %s" % sub_info.challenge_names)

            for c in sub_info.challenge_names:
                if not c in compat.available_submit:
                    msg = 'The challenge "%s" does not exist among %s.' % (c, list(compat.available_submit),)
                    raise UserError(msg)
                if not c in compat.compatible:
                    msg = 'The challenge "%s" is not compatible with protocols %s .' % (
                        c,
                        sub_info.protocols,
                    )
                    raise UserError(msg)
            username = get_dockerhub_username()

            print("")
            print("")
            br = submission_build(username=username, registry=registry, no_cache=parsed.no_cache)

            data = {
                "image": dataclasses.asdict(br),
                "user_label": sub_info.user_label,
                "user_payload": sub_info.user_metadata,
                "protocols": sub_info.protocols,
            }

            submit_to_challenges = sub_info.challenge_names

            if parsed.retire_same_label and sub_info.user_label:

                retired = dtserver_retire_same_label(
                    token=token, impersonate=impersonate, label=sub_info.user_label
                )
                if retired:
                    print(f"I retired the following submissions with the same label: {retired}")
                else:
                    print(f"No submissions with the same label available.")

            data = dtserver_submit2(
                token=token, challenges=submit_to_challenges, data=data, impersonate=impersonate,
            )

            # print('obtained:\n%s' % json.dumps(data, indent=2))
            component_id = data["component_id"]
            submissions = data["submissions"]
            # url_component = href(get_duckietown_server_url() + '/humans/components/%s' % component_id)

            msg = f"""
    
    Successfully created component.
    
    This component has been entered in {len(submissions)} challenge(s).
    
            """

            for challenge_name, sub_info2 in submissions.items():
                submission_id = sub_info2["submission_id"]
                url_submission = href(get_duckietown_server_url() + "/humans/submissions/%s" % submission_id)
                challenge_title = sub_info2["challenge"]["title"]
                submission_id_color = termcolor.colored(submission_id, "cyan")
                P = dark("$")
                head = bright(f"## Challenge {challenge_name} - {challenge_title}")
                msg += (
                    "\n\n"
                    + f"""
                
    {head}
    
    Track this submission at:
    
        {url_submission}
             
    You can follow its fate using:
    
        {P} dts challenges follow --submission {submission_id_color}
        
    You can speed up the evaluation using your own evaluator:
    
        {P} dts challenges evaluator --submission {submission_id_color}
        
    """.strip()
                )
                manual = href("https://docs.duckietown.org/daffy/AIDO/out/")
                msg += f"""
    
    For more information, see the manual at {manual}
    """

            shell.sprint(msg)

        extra = set(submissions) - set(submit_to_challenges)

        def cute_list(x):
            return ", ".join(x)

        if extra:
            msg = f"""
Note that the additional {len(extra)} challenges ({cute_list(extra)}) are required checks 
before running the code on the challenges you chose ({cute_list(submit_to_challenges)}).
"""
            shell.sprint(msg)


def bright(x):
    return termcolor.colored(x, "blue")


def dark(x):
    return termcolor.colored(x, attrs=["dark"])


def href(x):
    return termcolor.colored(x, "blue", attrs=["underline"])


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
