import os
import re
import json
import argparse
import io, sys
from dt_shell import DTCommandAbs, dtslogger
from diagnostics.utils import NotSupportedException


class DTCommand(DTCommandAbs):

    help = 'Runs the diagnostics tool and shows the outcome'


    @staticmethod
    def command(shell, args):
        # configure arguments
        parser = argparse.ArgumentParser()
        parser.add_argument('--robot',
                            default=None,
                            help="Name of the robot to run the diagnostics on")
        parser.add_argument('--project',
                            default=False,
                            action="store_true",
                            help="Whether to run diagnostics on the project in the cwd")
        parsed, _ = parser.parse_known_args(args=args)
        # ---
        tests = shell.include.diagnostics.info.discover_tests()

        print(tests)

        diagnostics = {
            'local' : {},
            'robot' : {}
        }

        tests = {
            test_name: shell.include.diagnostics.info.load_test(test_name)
            for test_name in tests
        }
        loaded_tests = list(filter(lambda x: x[1] is not None, tests.items()))



        local_diag = {}
        for test_name, test in loaded_tests:
            try:
                local_diag[test_name] = test.run_local(shell, args, parsed)
            except NotSupportedException:
                pass
            except:
                dtslogger.warning(sys.exc_info()[0], exc_info=True)

        robot_diag = {}
        for test_name, test in loaded_tests:
            try:
                robot_diag[test_name] = test.run_robot(shell, args, parsed)
            except NotSupportedException:
                pass
            except:
                dtslogger.warning(sys.exc_info()[0], exc_info=True)



        # merge diagnostics
        where_to_dict = {'local': local_diag, 'robot': robot_diag}
        for where, diag in where_to_dict.items():
            for test, result in diag.items():
                cur = diagnostics[where]
                keys = test.split('/')
                for k in keys[:-1]:
                    if k not in cur:
                        cur[k] = {}
                    cur = cur[k]
                cur[keys[-1]] = result

        # compressed
        # print(json.dumps(diagnostics))
        import zlib
        print(json.dumps(diagnostics, indent=4, sort_keys=True))

        with open('./diag.zlib', 'wb') as fout:
            fout.write(zlib.compress(json.dumps(diagnostics).encode()))



    @staticmethod
    def complete(shell, word, line):
        return []


def add_to_diagnostics(diag, test, result):
    cur = diag
    keys = test.split('/')
    for k in keys:
        if k not in cur:
            cur[k] = {}
        cur = cur[k]
    cur
