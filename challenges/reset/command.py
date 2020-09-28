import argparse

from challenges.challenges_cmd_utils import check_duckietown_challenges_version, wrap_server_operations
from dt_shell import DTCommandAbs, DTShell, UserError


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        check_duckietown_challenges_version()

        token = shell.get_dt1_token()
        parser = argparse.ArgumentParser(prog="dts challenges reset")
        parser.add_argument("--job", default=None, help="Only reset this particular job", type=int)
        parser.add_argument(
            "--submission", default=None, type=int, help="Reset this particular submission",
        )
        parser.add_argument("--step", default=None, help="Only reset this particular step")
        parser.add_argument("--impersonate", default=None)
        parsed = parser.parse_args(args)

        if parsed.submission is None and parsed.job is None:
            msg = "You need to specify either --job or --submission."
            raise UserError(msg)

        with wrap_server_operations():
            if parsed.submission is not None:
                from duckietown_challenges.rest_methods import dtserver_reset_submission

                submission_id = dtserver_reset_submission(
                    token,
                    submission_id=parsed.submission,
                    impersonate=parsed.impersonate,
                    step_name=parsed.step,
                )
                shell.sprint("Successfully reset %s" % submission_id)
            elif parsed.job is not None:
                from duckietown_challenges.rest_methods import dtserver_reset_job

                job_id = dtserver_reset_job(token, job_id=parsed.job, impersonate=parsed.impersonate)
                shell.sprint("Successfully reset %s" % job_id)
            else:
                assert False
