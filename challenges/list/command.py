import re

import termcolor
from dt_shell import DTCommandAbs



class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        token = shell.get_dt1_token()
        from duckietown_challenges.rest_methods import dtserver_get_user_submissions

        submissions = dtserver_get_user_submissions(token)

        def key(x):
            return submissions[x]['date_submitted']

        challenge_id2name = {}
        for submission in submissions.values():
            challenge_id = submission['challenge_id']
            challenge_name = submission.get('challenge_name', '%s' % challenge_id)
            challenge_id2name[challenge_id] = challenge_name

        challenges = sorted(challenge_id2name)
        out = []

        for challenge_id in challenges:
            out.append('')
            out.append(bold('Challenge %s' % challenge_id2name[challenge_id]))
            out.append('')
            for submission_id in sorted(submissions, key=key):
                submission = submissions[submission_id]

                if submission['challenge_id'] != challenge_id:
                    continue

                def d(dt):
                    return dt.strftime("%Y-%m-%d %H:%M")

                from duckietown_challenges import get_duckietown_server_url
                server = get_duckietown_server_url()

                url = server + '/humans/submissions/%s' % submission_id

                user_label = submission.get('user_label', None) or dark('(no user label)')

                M = 30
                if len(user_label) > M:
                    user_label = user_label[:M - 5] + ' ...'

                user_label = user_label.ljust(M)

                s = ('%4s  %s  %10s %s  %s' % (submission_id,
                                               d(submission['date_submitted']),
                                               pad_to_screen_length(colored_status(submission['status']), 10),
                                               user_label,

                                               href(url)))

                out.append(s)
            out.append('')

        msg = u"\n".join(out)
        if hasattr(shell, 'sprint'):
            shell.sprint(msg)
        else:
            print(msg)


def colored_status(status):
    return termcolor.colored(status, color_status(status))


def color_status(s):
    colors = {
        'success': 'green',
        'evaluating': 'blue',
        'failed': 'red',
        'retired': 'cyan',
        'error': 'red',
    }

    if s in colors:
        return colors[s]
    else:
        return 'white'


def href(x):
    return termcolor.colored(x, 'blue', attrs=['underline'])


def bold(x):
    return termcolor.colored(x, 'white', attrs=['bold'])


def dark(x):
    return termcolor.colored(x, attrs=['dark'])


def remove_escapes(s):
    escape = re.compile('\x1b\[..?m')
    return escape.sub("", s)


def get_length_on_screen(s):
    """ Returns the length of s without the escapes """
    return len(remove_escapes(s))


def pad_to_screen_length(s, desired_screen_length,
                         pad=" ", last=None,
                         align_right=False):
    """
        Pads a string so that it will appear of the given size
        on the terminal.

        align_right: aligns right instead of left (default)
    """
    assert isinstance(desired_screen_length, int)
    # todo: assert pad = 1
    current_size = get_length_on_screen(s)

    if last is None:
        last = pad

    if current_size < desired_screen_length:
        nadd = (desired_screen_length - current_size)
        padding = (pad * (nadd - 1))
        if align_right:
            s = last + padding + s
        else:
            s = s + padding + last

    # if debug_padding:
    #     if current_size > desired_screen_length:
    #         T = '(cut)'
    #         s = s[:desired_screen_length - len(T)] + T

    return s
