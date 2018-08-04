from __future__ import print_function
from dt_shell import DTCommandAbs

class DTCommand(DTCommandAbs):
    config_key = 'aido18'
    config = {
        'host': {
            'text': 'Dashboard hostname',
            'default': 'http://localhost:8080/'
            # 'default' : 'http://dashboard.duckietown.org'
        },
        'api_version': {
            'text': 'API version',
            'default': '1.0'
        },
        'app_id': {
            'text': 'Your API Application ID',
            'default': ''
        },
        'app_secret': {
            'text': 'Your API Application Secret',
            'default': ''
        }
    }
    config_key_order = ['host', 'api_version', 'app_id', 'app_secret']

    @staticmethod
    def command(shell, args):
        app_id = None
        app_secret = None
        # get config
        config = {}
        for k in DTCommand.config_key_order:
            val = DTCommand.config[k]['default']
            if DTCommand.config_key in shell.config and k in shell.config[DTCommand.config_key]:
                val = shell.config[DTCommand.config_key][k]
            msg = '%s%s: ' % (
                DTCommand.config[k]['text'],
                ' [current: %s]' % val if len(val.strip()) > 0 else ''
            )

            # TODO: validate host and add http://
            val_in = raw_input(msg)

            shell.config[DTCommand.config_key][k] = val_in if len(val_in.strip()) > 0 else val
        # commit
        shell.save_config()
        print('OK')
