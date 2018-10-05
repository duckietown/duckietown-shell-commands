import argparse
import os

import yaml
from dt_shell import DTCommandAbs
from dt_shell.remote import dtserver_challenge_define


class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, args):
        try:
            from duckietown_challenges.challenge import ChallengeDescription
        except ImportError as e:
            msg = 'You need to install or update duckietown-challenges:\n%s' % e
            raise Exception(msg)

        token = shell.get_dt1_token()

        parser = argparse.ArgumentParser()
        parser.add_argument('--config', required=True,
                            help="YAML configuration file")
        parser.add_argument('--make-sha', dest='make_sha', default=False, action='store_true')
        parsed = parser.parse_args(args)

        fn = os.path.join(parsed.config)
        if not os.path.exists(fn):
            msg = 'File %s does not exist.' % fn
            raise Exception(msg)

        # basename = os.path.basename(os.path.splitext(fn)[0])
        contents = open(fn).read()
        data = yaml.load(contents)

        challenge = ChallengeDescription.from_yaml(data)

        if parsed.make_sha:
            for step in challenge.steps.values():
                step.update_container()

        data2 = yaml.dump(challenge.as_dict())

        challenge_id = dtserver_challenge_define(token, data2)
        print('created challenge %s' % challenge_id)
