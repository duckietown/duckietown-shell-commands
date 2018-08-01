from dt_shell import DTCommandAbs

class DTCommand(DTCommandAbs):

    @staticmethod
    def command(shell, line):
        app_id = None
        app_secret = None
        # get config
        if 'aido18' in shell.config:
            if 'app_id' in shell.config['aido18']: app_id = shell.config['aido18']['app_id']
            if 'app_secret' in shell.config['aido18']: app_secret = shell.config['aido18']['app_secret']
        else:
            shell.config['aido18'] = {}
        # get app_id
        msg = 'Your Application ID%s: ' % (' [%s]'%app_id if app_id is not None else '')
        app_id_in = raw_input(msg)
        app_id = app_id_in if len(app_id_in.strip()) > 0 else app_id
        # get app_secret
        msg = 'Your Application Secret%s: ' % (' [%s]'%app_secret if app_secret is not None else '')
        app_secret_in = raw_input(msg)
        app_secret = app_secret_in if len(app_secret_in.strip()) > 0 else app_secret
        # store app_id and app_secret
        shell.config['aido18']['app_id'] = app_id
        shell.config['aido18']['app_secret'] = app_secret
        # commit
        shell.save_config()
        print 'OK'
