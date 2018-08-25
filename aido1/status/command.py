from __future__ import print_function
from dt_shell import DTCommandAbs



class DTCommand(DTCommandAbs):

    compose = None

    @staticmethod
    def init(shell):
        if DTCommand.compose is None:
            from compose_python import Compose
            from texttable import Texttable
            app_id = None
            app_secret = None
            # get config
            if 'aido18' not in shell.config:
                print('Command `aido18` not initialized yet. Type `aido18 init`.')
                return
            host = shell.config['aido18']['host']
            api_version = shell.config['aido18']['api_version']
            app_id = shell.config['aido18']['app_id']
            app_secret = shell.config['aido18']['app_secret']
            # create compose object
            res = Compose( host, app_id, app_secret, version=api_version )
            if not res.initialized: return False
            DTCommand.compose = res
        return True

    @staticmethod
    def command(shell, args):
        if not DTCommand.init( shell ): return
        # make sure that this key has access to the endpoint
        DTCommand.compose.is_endpoint_available('submission/list')
        if not DTCommand.compose.is_endpoint_available('submission/list'):
            print('The endpoint `submission/list` is not accessible to the given API Application. ', end='')
            print('Please enable it on `%s`' % shell.config['aido18']['host'])
            return
        # get list of submissions
        success, data, msg = DTCommand.compose.submission.list()
        if not success: print(msg); return
        # draw table
        t = Texttable()
        t.header(['ID', 'Label', 'Submitted', 'Status'])
        for submission in data['submissions']:
            t.add_row( [ submission['id'], submission['label'], submission['datetime'], submission['status'] ] )
        print(t.draw())
