import copy
import logging
import os
import re
import sys
import time
import traceback
from itertools import product
from threading import Thread
from typing import List, Tuple, Any, Type
from collections import OrderedDict

from dt_shell import DTCommandAbs, DTShell, dtslogger


VERBOSE_ARG = '-vvv'


class MultiCommand(object):

    def __init__(self, command: Type[DTCommandAbs], shell: DTShell,
                 multiargs: List[Tuple[str, ...]], args: List[str]):
        self._command = command
        self._shell = shell
        self._multiargs = multiargs
        self._args = args
        self._keys = []
        self._values = []
        self._verbose = VERBOSE_ARG in self._args
        if self._verbose:
            self._args.remove(VERBOSE_ARG)
        # make sure this is not a recursive call
        if '__multiarg__' in args:
            args.remove('__multiarg__')
            return
        # parse args
        self._parse_args()
        config_str = '\n\t'.join(list(map(str, self._get_args())))
        dtslogger.debug(f"Multi-Arg Config: \n\t{config_str}")

    @property
    def is_multicommand(self):
        return len(self._values) > 1

    def execute(self):
        workers = []
        for args in self._get_args():
            dtslogger.warning(f' =====> Multi-Arg: Running with args: {args}')
            args.append('__multiarg__')
            worker = Thread(target=self._execute_single, args=(args,))
            workers.append(worker)
        # disable logging
        if not self._verbose:
            _sys_stdout = sys.stdout
            _dev_null = open(os.devnull, 'w')
            sys.stdout = _dev_null
            _log_level = dtslogger.level
            dtslogger.setLevel(logging.WARNING)
        # start workers
        for w in workers:
            w.start()
        # wait for them to finish
        for w in workers:
            w.join()
        # ---
        if not self._verbose:
            _dev_null.close()
            sys.stdout = _sys_stdout
            dtslogger.setLevel(_log_level)

    def _log(self, msg):
        dtslogger.setLevel(logging.INFO)
        dtslogger.info(msg)
        dtslogger.setLevel(logging.ERROR)

    def _execute_single(self, args):
        try:
            self._command.command(self._shell, args)
        except KeyboardInterrupt:
            dtslogger.error(f'   <===== Multi-Arg: Aborted with args: {args}')
        except BaseException:
            # printing stack trace
            traceback.print_exc()
            time.sleep(0.1)
            dtslogger.error(f'   <===== Multi-Arg:  Failed with args: {args}')
        self._log(f'    <===== Multi-Arg: Success with args: {args}')

    def _get_args(self):
        args = [copy.deepcopy(self._args) for _ in range(len(self._values))]
        for i, values in enumerate(self._values):
            for j, value in enumerate(values):
                key = self._keys[j]
                args[i][self._args.index(key) + 1] = value
        return args

    def _parse_args(self):
        values = OrderedDict()
        for margs in self._multiargs:
            present = [marg for marg in margs if marg in self._args]
            if len(present) == 0:
                continue
            if len(present) > 1:
                dtslogger.error(f"You cannot use the arguments {','.join(present)} together.")
                return
            # get argument value
            marg = present[0]
            try:
                marg_idx = self._args.index(marg)
                marg_value = self._args[marg_idx + 1]
            except IndexError:
                dtslogger.error(f"You need to provide a value for {marg}.")
                return
            # parse values
            values[marg] = self._parse_values(marg_value)
        # combine values into a list of tuples
        self._keys = list(values.keys())
        self._values = list(product(*values.values()))

    @staticmethod
    def _parse_values(arg_value: str) -> List[Any]:
        arg_value = str(arg_value)
        match = re.match("^.*{([^}]+)}.*$", arg_value)
        if not match:
            return [arg_value]
        s, f = arg_value.index('{'), arg_value.index('}') + 1
        domain = match.group(1)
        patterns = {
            r"^(\d)+\-(\d)+$": lambda m: list(range(int(m.group(1)), int(m.group(2)) + 1, 1)),
            r"^(\d)+(\,(\d)+)*$": lambda m: list(map(int, m.group(0).split(',')))
        }
        for pattern, parser in patterns.items():
            match = re.match(pattern, domain)
            skeleton = lambda vs: [f"{arg_value[:s]}{v}{arg_value[f:]}" for v in vs]
            if match is None:
                continue
            try:
                values = parser(match)
            except ValueError:
                dtslogger.error(f'Error parsing multi-arg value "{domain}".')
                return []
            return skeleton(values)
