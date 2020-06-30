"""Utility providing useful functions used to communicate to the duckiebot via ssh"""

import paramiko
from scp import SCPClient
import sys
import re
import time


def line_buffered(pseudo_fs):
    """splits chars from a pseudo filesystem into line, whis is yealded as iterable"""
    channel = pseudo_fs.channel
    line_buf = ""
    while not channel.closed or channel.recv_ready() or channel.recv_stderr_ready():
        c = pseudo_fs.read(1).decode("utf-8") 
        line_buf += c
        if line_buf.endswith('\n'):
            yield line_buf
            line_buf = ''
            
class SSHUtils:
    def __init__(self, botname, username=None, password=None):
        self.botname = botname
        self.username = username if username is not None else 'duckie'
        self.password = password if password is not None else 'quackquack'

    def _createSSHClient(self):
        """creates a new parmike ssh client"""
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(self.botname+'.local', 22, self.username, self.password)
        return client

    def put(self, filename):
        """puts local file on the client"""
        ssh = self._createSSHClient()
        scp = SCPClient(ssh.get_transport())
        scp.put(filename)
    
    def get(self, filename):
        """retrieves local file from the client"""
        ssh = self._createSSHClient()
        scp = SCPClient(ssh.get_transport())
        scp.get(filename)

    def command(self, command, regex=[], callback=[], detect_input=True, onlyOnce=[]):
        """ Executes command on ssh client

        Args:
            command (string): command to be executed on the client
            regex (list, optional): if the regex is detected, the corresponding callback function is called. Defaults to [].
            callback (list, optional): list of fuctions to be executed , triggered ba regex. Defaults to [].
            detect_input (bool, optional): Wheter to analyze the command output (stdout) or not. Defaults to True.
            onlyOnce (list, optional): list wheter the resp. callback should only be called once. Defaults to [].
        """
        regex = list(regex)
        callback = list(callback)
        onlyOnce = list(onlyOnce)
        assert(len(regex) == len(callback) and (len(onlyOnce) == 0 or len(onlyOnce) == len(regex)))

        called =  [False]*len(regex)
        ssh = self._createSSHClient()

        sin,sout,serr = ssh.exec_command(command)

        if detect_input:
            for line in line_buffered(sout):
                sys.stdout.write(line)
                if regex is not [] and callback is not []:
                    for index, r in enumerate(regex):
                        if re.search(r, line):
                            print(r + " found in line " + line)
                            if  (len(onlyOnce) == 0 or not onlyOnce[index] or (onlyOnce[index] and not called[index])):
                                called[index] = True
                                callback[index](line)

        for l in line_buffered(serr):
            sys.stdout.write(l)
        while int(sout.channel.recv_exit_status()) != 0:
            time.sleep(1)
    