from dt_shell import DTCommandAbs
from compose_python import Compose
from texttable import Texttable

class DTCommand(DTCommandAbs):

    compose = None

    @staticmethod
    def init(shell):
        if DTCommand.compose is None:
            app_id = None
            app_secret = None
            # get config
            if 'aido18' not in shell.config:
                print 'Command `aido18` not initialized yet. Type `aido18 init`.'
                return
            host = shell.config['aido18']['host']
            api_version = shell.config['aido18']['api_version']
            app_id = shell.config['aido18']['app_id']
            app_secret = shell.config['aido18']['app_secret']
            # create compose object
            DTCommand.compose = Compose( host, api_version, app_id, app_secret )

    @staticmethod
    def command(shell, args):
        DTCommand.init( shell )
        # get list of submissions
        submissions = DTCommand.compose.submission.list()
        #
        print submissions

        # t = Texttable()
        # t.add_rows([['Name', 'Age'], ['Alice', 24], ['Bob', 19]])
        # print t.draw()
