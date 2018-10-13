import argparse
import datetime
import sys
import time
from collections import defaultdict

import termcolor
from dt_shell import DTCommandAbs
from dt_shell.remote import make_server_request

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
    previous_s = None

    print()
    while True:
        try:
            data = get_info(token, submission_id)
        except Exception as e:
            print(e)
            time.sleep(5)
            continue
        # print json.dumps(data, indent=4)
        status_details = data['status-details']
        complete = status_details['complete']
        result = status_details['result']
        step2status = status_details['step2status']
        step2status.pop('START', None)

        step2job = status_details['step2job']
        for k, v in step2job.items():
            if k not in step2job_seen or step2job_seen[k] != v:
                step2job_seen[k] = v

                print('\nJob "%s" created for step %s' % (v, k))

        for k, v in step2status.items():
            if k not in step2status_seen or step2status_seen[k] != v:
                step2status_seen[k] = v

                print('\nStep "%s" is in state %s' % (k, v))

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

        cs.append('status: %s' % color_status(data['status']))

        if step2status:

            for step_name, step_state in step2status.items():
                cs.append('%s: %s' % (step_name, color_status(step_state)))

        if next_steps:
            cs.append("  In queue: %s" % " ".join(map(str, next_steps)))

        s = '  '.join(cs)

        now = datetime.datetime.now()
        sys.stdout.write('\r' + ' ' * 80 + '\r')
        sys.stdout.write(now.isoformat()[-15:-7] + ' ' + s)
        sys.stdout.flush()
        time.sleep(5)


def color_status(x):
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


def get_info(token, submission_id):
    endpoint = '/submission/%s' % submission_id
    method = 'GET'
    data = {}
    return make_server_request(token, endpoint, data=data, method=method)
