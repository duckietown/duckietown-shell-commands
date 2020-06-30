"""CLI in order to run the bm"""
import argparse
from benchmark import Benchmark

PM_SUBGROUP = 'new_test'
BOTNAME = 'autobot14'
DURATION = 150
# TODO: local option

def run():
    parser = argparse.ArgumentParser(description='Run a Hardware benchmark on a duckiebot')
    parser.add_argument('BOT_TYPE',
                        help='bot type, e.g. DB18p4')
    parser.add_argument('BATTERY_TYPE',
                        help='battery type e.g. Old Alu')
    parser.add_argument('VERSION', default='master19',
                        help='software version (master19 or daffy)')
    parser.add_argument('BOTNAME',
                        help='hostname of the bot without .local')
    parser.add_argument('-d','--duration', dest='duration', default=150, type=int,
                        help='benchmark duration, (at least 150)')
    parser.add_argument('-f','--bm_file', dest='bm_file', default='assets/pre_bm.py',
                        help='benchmark file to be executed on the bot')
    parser.add_argument('-g','--group', dest='group', default='test',
                        help='benchmark subgroup (default test)')
    parser.add_argument('-s','--subgroup', dest='subgroup', default='new_test',
                        help='benchmark subgroup (default new_test')

    args = parser.parse_args()
    bm = Benchmark(args.BOTNAME, args.VERSION, args.duration, args.group, args.subgroup, args.bm_file, args.BATTERY_TYPE, args.BOT_TYPE)
    bm.run()

if __name__ == "__main__":
    run()
