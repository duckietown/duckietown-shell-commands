import subprocess
import re
import sys
import asyncio
import select
import os
import pty
import time
import signal

import nest_asyncio
nest_asyncio.apply()


def _line_buffered(pseudo_fs, read_fc):
    """splits chars from a pseudo filesystem into line, whis is yealded as iterable"""
    line_buf = ""

    for c in iter(lambda: read_fc(pseudo_fs), ''):
        line_buf += c
        if line_buf.endswith('\n'):
            yield line_buf
            line_buf = ''

def _analyze_line(process, line, regex, callback, onlyOnce, called, afterCallback, afterLineRegex):
    """analyzing a line, callinga callback if regex is found"""
    sys.stdout.write(line)
    if  'Done!' in line or 'Bye bye!' in line:
        killProcess(process)
        return True
    if afterLineRegex and re.search(afterLineRegex, line): # if this regex is found, call the after callback.
        afterCallback()
    if regex is not [] and callback is not []:
        for index, r in enumerate(regex):
            if re.search(r, line): # if regex is found, call the callback
                if  (len(onlyOnce) == 0 or not onlyOnce[index] or (onlyOnce[index] and not called[index])):
                    called[index] = True
                    callback[index](line)
    return False

def killProcess(process): 
    """kill the subprocess"""
    os.killpg(os.getpgid(process.pid), signal.SIGTERM)

async def _async_command(command, regex, callback, detect_input, onlyOnce, afterCommand, afterLineRegex): 
    """general command executed locally on the machine"""   
    called =  [False]*len(regex)
    process = subprocess.Popen([command], stderr=subprocess.PIPE, stdout=subprocess.PIPE, stdin=subprocess.PIPE, shell=True, preexec_fn=os.setsid)

    if detect_input:
        for line in _line_buffered(process, lambda pseudo_fs: pseudo_fs.stdout.read(1).decode("utf-8")):
            if _analyze_line(process, line, regex, callback, onlyOnce, called, afterCommand, afterLineRegex):
                break
            
async def _async_docker_command(command, regex, callback, detect_input, onlyOnce, afterCommand, afterLineRegex):
    """command optimized for docker and dts environments executed locally on the machine"""   
    called =  [False]*len(regex)
    master, tty = pty.openpty()
    process = subprocess.Popen([command], stdin=tty, stdout=tty, stderr=tty, shell=True, preexec_fn=os.setsid)
    stopped = False

    if detect_input:
        while process.poll() is None and not stopped:
            # Watch two files, STDIN of your Python process and the pseudo terminal
            r, _, _ = select.select([sys.stdin, master], [], [])
            if master in r:
                for line in _line_buffered(master, lambda pseudo_fs: os.read(pseudo_fs, 1).decode("utf-8")):
                    stopped = _analyze_line(process, line, regex, callback, onlyOnce, called, lambda: os.write(master, (afterCommand+"\n").encode('utf-8')), afterLineRegex)
                    if stopped:
                        break

def command(command, regex=None, callback=None, detect_input=True, onlyOnce=None, forceDocker=False, afterCommand=None, afterLineRegex=None):
    """function to be called, which in turn calls the corresponding command functions
        TODO: execute callbacks in different threads

    Args:
        command (string): command to be executed on the client
        regex (list, optional): if the regex is detected, the corresponding callback function is called. Defaults to [].
        callback (list, optional): list of functions to be executed , triggered ba regex. Defaults to [].
        detect_input (bool, optional): Whether to analyze the command output (stdout) or not. Defaults to True.
        onlyOnce (list, optional): list whether the resp. callback should only be called once. Defaults to [].
        forceDocker (bool, optional): manually trigger the use of the docker optimized version. Defaults to False.
        afterCommand (string, optional): command to be executed after the afterLineRegex is found. Defaults to None.
        afterLineRegex (regex, optional): decides when to execute the after command. Defaults to None.
    """

    if regex is None:
        regex=[]
    if callback is None:
        callback=[]
    if onlyOnce is None:
        onlyOnce=[]

    assert(len(regex) == len(callback))
    assert(len(onlyOnce) == 0 or len(onlyOnce) == len(regex))

    print("Executing Command: "  + command)


    loop = asyncio.get_event_loop()
    loop.run_until_complete(_async_docker_command(command, regex, callback, detect_input, onlyOnce, afterCommand, afterLineRegex)
                            if 'docker' in command or 'dts' in command or forceDocker else 
                            _async_command(command, regex, callback, detect_input, onlyOnce, afterCommand, afterLineRegex))