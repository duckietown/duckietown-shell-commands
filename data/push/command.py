import os
import argparse
import requests

from dt_shell import DTCommandAbs, dtslogger
from utils.cli_utils import start_command_in_subprocess

DATA_API_ACTION = "put_object"

DATA_API_URL_FMT = "https://data.duckietown.org/v1/{action}/{bucket}/{object}"
DATA_API_URL = lambda action, bucket, object: \
    DATA_API_URL_FMT.format(action=action, bucket=bucket, object=object)
BUCKET_FMT = lambda visibility: f"duckietown-{visibility}-storage"

VALID_BUCKETS = [
    'duckietown-public-storage',
    'duckietown-private-storage'
]


class DTCommand(DTCommandAbs):

    help = 'Uploads an object (file) to the Duckietown Cloud Storage space'

    usage = '''
Usage:

    dts data push --bucket duckietown-<visibility>-storage <file> <object>
    
OR

    dts data push <file> [<visibility>:]<object>
    
Where <visibility> can be one of [public, private].
'''

    @staticmethod
    def command(shell, args):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument('-B', '--bucket', default=None, choices=VALID_BUCKETS,
                            help="Bucket the object should be uploaded to")
        parser.add_argument('file', nargs=1)
        parser.add_argument('object', nargs=1)
        parsed, _ = parser.parse_known_args(args=args)
        # ---
        parsed.file = parsed.file[0]
        parsed.object = parsed.object[0]
        # check arguments
        ## use the format [bucket_visibility]:[object] as a short for
        ##      --bucket duckietown-[bucket_visibility]-storage [object]
        arg1, arg2, *acc = (parsed.object + ':_').split(':')
        # handle invalid formats
        if len(acc) > 1:
            dtslogger.error("Invalid format for argument 'object'.")
            print(DTCommand.usage)
            exit(1)
        # parse args
        bucket_vis, object_path = (arg1, arg2) if arg2 != '_' else (None, arg1)
        # make sure that the bucket is given in at least one form
        if bucket_vis is None and parsed.bucket is None:
            dtslogger.error('You must specify a destination bucket for the object.')
            print(DTCommand.usage)
            exit(2)
        # make sure that at most one bucket is given
        if bucket_vis is not None and parsed.bucket is not None:
            dtslogger.error('You can specify at most one bucket as destination for the object.')
            print(DTCommand.usage)
            exit(3)
        # validate bucket
        if bucket_vis is not None and bucket_vis not in ['public', 'private']:
            dtslogger.error("Bucket (short format) can be either 'public' or 'private'.")
            print(DTCommand.usage)
            exit(4)
        # converge args to parsed
        parsed.object = object_path
        if bucket_vis:
            parsed.bucket = BUCKET_FMT(bucket_vis)
        # make sure that the input file exists
        if not os.path.isfile(parsed.file):
            dtslogger.error(f"File '{parsed.file}' not found!")
            exit(5)
        # sanitize file path
        parsed.file = os.path.abspath(parsed.file)
        # make sure that the token is set
        token = shell.get_dt1_token()
        # request authorization to perform action
        dtslogger.info('Authorizing request...')
        data_api_url = DATA_API_URL(DATA_API_ACTION, parsed.bucket, parsed.object)
        res = requests.get(data_api_url, headers={'X-Duckietown-Token': token})
        if res.status_code != 200:
            dtslogger.error(res.reason)
            exit(100)
        # parse answer
        answer = res.json()
        if answer['code'] != 200:
            dtslogger.error(answer['message'])
            exit(answer['code'])
        # request authorized
        signed_url = answer['data']['url']
        dtslogger.info('Uploading file...')
        start_command_in_subprocess(' '.join([
            'curl', '--progress-bar',
            '--request', 'PUT',
            '--upload-file', parsed.file,
            f'"{signed_url}"',
            '|', 'tee'
        ]))
