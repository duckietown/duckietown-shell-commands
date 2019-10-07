import os
import re
import json
import argparse
import io, sys
from glob import glob
import importlib.util
from dt_shell import DTCommandAbs, dtslogger



class DTCommand(DTCommandAbs):

    help = 'Shows the list of tests that a diagnostics would run'


    @staticmethod
    def command(shell, args):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument('--grep', default=None,
                            help="Show only tests containing this text")
        parsed, _ = parser.parse_known_args(args=args)
        # ---


    @staticmethod
    def complete(shell, word, line):
        return []

    @staticmethod
    def discover_tests():
        tests_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'dt_tests')
        # discover tests
        tests = glob(os.path.join(tests_path, '**', 'index.py'), recursive=True)
        return list(map(lambda x: os.path.relpath(x, tests_path).replace('/index.py', ''), tests))

    @staticmethod
    def load_test(name):
        try:
            test_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'dt_tests', name, 'index.py')
            spec = importlib.util.spec_from_file_location("shell.version", test_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            test = mod.DiagnosticsTest()
            if not test._dt_test_fingerprint():
                return None
            return test
        except:
            return None
