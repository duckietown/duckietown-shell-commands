import argparse
import datetime
import sys
import time
from collections import defaultdict

import termcolor

from dt_shell import DTCommandAbs
from duckietown_challenges.rest_methods import dtserver_get_info

usage = """

To follow the fate of the submission, use:

    %(prog)s --submission ID


"""


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        prog = 'dts challenges follow'

        parser = argparse.ArgumentParser(prog=prog, usage=usage)
        parser.add_argument('--submission', required=True, type=int)
        parsed = parser.parse_args(args)

        token = shell.get_dt1_token()

        submission_id = parsed.submission

        follow_submission(token, submission_id)


def follow_submission(token, submission_id):
    step2job_seen = {}
    step2status_seen = defaultdict(lambda: "")

    print('')
    while True:
        try:
            data = dtserver_get_info(token, submission_id)
        except BaseException as e:
            print(e)
            time.sleep(5)
            continue
        # print json.dumps(data, indent=4)

        status_details = data['status-details']
        if status_details is None:
            write_status_line('Not processed yet.')
        else:

            complete = status_details['complete']
            result = status_details['result']
            step2status = status_details['step2status']
            step2status.pop('START', None)

            step2job = status_details['step2job']
            for k, v in step2job.items():
                if k not in step2job_seen or step2job_seen[k] != v:
                    step2job_seen[k] = v

                    write_status_line('Job "%s" created for step %s' % (v, k))

            for k, v in step2status.items():
                if k not in step2status_seen or step2status_seen[k] != v:
                    step2status_seen[k] = v

                    write_status_line('Step "%s" is in state %s' % (k, v))

            next_steps = status_details['next_steps']

            # if complete:
            #     msg = 'The submission is complete with result "%s".' % result
            #     print(msg)
            #     break
            cs = []

            if complete:
                cs.append('complete')
            else:
                cs.append('please wait')

            cs.append('status: %s' % color_status(status_details['result']))

            if step2status:

                for step_name, step_state in step2status.items():
                    cs.append('%s: %s' % (step_name, color_status(step_state)))

            if next_steps:
                cs.append("  In queue: %s" % " ".join(map(str, next_steps)))

            s = '  '.join(cs)
            write_status_line(s)

        time.sleep(10)


class Storage:
    previous = None


def write_status_line(x):
    if x == Storage.previous:
        sys.stdout.write('\r' + ' ' * 80 + '\r')
    else:
        sys.stdout.write('\n')
    now = datetime.datetime.now()
    n = termcolor.colored(now.isoformat()[-15:-7], 'blue', attrs=['dark'])
    sys.stdout.write(' - ' + n + '   ' + x)
    sys.stdout.flush()
    Storage.previous = x


def color_status(x: str):

    status2color = {
        'failed': dict(color='red', on_color=None, attrs=None),
        'error': dict(color='red', on_color=None, attrs=None),
        'success': dict(color='green', on_color=None, attrs=None),
        'evaluating': dict(color='blue', on_color=None, attrs=None),
        'aborted': dict(color='cyan', on_color=None, attrs=['dark']),
        'timeout': dict(color='cyan', on_color=None, attrs=['dark']),
    }

    if x in status2color:
        return termcolor.colored(x, **status2color[x])
    else:
        return x
