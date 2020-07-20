
from .utils.ssh import SSHUtils
from .utils.local_command import command
from .secrets import APP_ID, APP_SECRET
import time
import re
import uuid
import requests
import json


class Benchmark:

    def __init__(self, botname, duration, bm_group, bm_subgroup, pre_bm_file, api_url):
        self.pre_bm_file = pre_bm_file
        self.bm_group = bm_group
        self.bm_subgroup = bm_subgroup
        self.botname = botname
        self.duration = duration
        self.api_url = api_url
        self.ssh = SSHUtils(self.botname)


    def _do_pre_bm(self):
        """executes the pre_bm file on the bot"""
        self.ssh.command('ls -la')
        self.ssh.command('rm ' + self.pre_bm_file.split('/')[-1])
        self.ssh.put(self.pre_bm_file)
        self.ssh.command('sudo pip install picamera')
        self.ssh.command('python ' + self.pre_bm_file.split('/')[-1])

    def _set_version(self, version='daffy'):
        """sets local dts version"""
        command('dts --set-version {}'.format(version), afterCommand="exit\n", afterLineRegex=r' to list commands.') #please bear with that command as it opens a dt shell

    def _sync_time(self):
        """syncs the time on the bot with the time server"""
        self.ssh.command('sudo service ntp stop && sudo ntpd -gq && sudo service ntp start')

    def _record_bags(self, bagname, version):
        """starts recording the rosbag with the topics  segment_list and lane_pose (latency)"""
        print('Recoreding Bags')
        self._set_version(version)
        cmd = 'dts duckiebot demo --demo_name base --duckiebot_name {}'.format(self.botname)
        command(cmd, afterCommand=('sudo mount -t vfat /dev/sda1 /mnt -o uid=1000,gid=1000 ' 
                                ' && rosbag record /{duckiename}/line_detector_node/segment_list /{duckiename}/lane_controller_node/lane_pose /{duckiename}/lane_filter_node/lane_pose /rosout -O /mnt/{bag_name} --duration {duration}'
                                ' && ls -la /mnt && exit').
                                format(duckiename=self.botname, bag_name=bagname, duration=self.duration-60),
                afterLineRegex=r'Set PYTHONPATH to: /home/software/catkin_ws/src:/opt/ros/kinetic/lib/python2.7/dist-packages:/home/software/catkin_ws/src')
    def _collect_meta(self):
        meta_req = requests.get('{}/hw_benchmark/meta'.format(self.api_url))
        if meta_req.status_code != 200:
            print('Benchmark API not reachable')
            exit(1)
        content = json.loads(meta_req.content)
        meta = {}
        for d in content['dropdowns']:
            msg = d['name'] + ': Please select '
            for i, c in enumerate(d['content']):
                msg += '[{}]=>{}, '.format(i+1, c)
            msg = msg[0:-2] + '\n\t> '
            index = int(input(msg)) - 1 
            if 0 > index or index > len(d['content']):
                print('Index doesn\'t exist')
                exit(1)
            meta[d['key']] = d['content'][index]
        
        for t in content['textfields']:
            meta[t['key']] = t['default']
            ipt = input('Please enter {}, default is {} \n\t> '.format(t['name'], t ['default']))
            if ipt != '':
                meta[t['key']] = ipt
        return meta

    def _start_lane_following(self):
        """ WIP start the lanefollowing"""
        CRED = '\033[4;35m'
        CEND = '\033[0m'

        cmd = 'dts duckiebot keyboard_control {} --cli'.format(self.botname)
        print(cmd)
        print(CRED + "\n\n\n\n\n START LANEFOLLOWING \n\n\n\n\n" +CEND)
        #command(cmd) TODO start automatic

    def _upload_to_api(self, diagnostics_id, latencies_bag_name, meta):
        """uploads the file to the hw benchmarkapi"""
        res = '{'
        for key, item in meta.items():
            res += '\\\"{}\\\":\\\"{}\\\",'.format(key, item)
        res = res[:-1]
        res += '}'
        
        cmd = (' sudo mount -t vfat /dev/sda1 /mnt -o uid=1000,gid=1000 '
               ' && curl -X POST "{api_url}/hw_benchmark/files/{id} "'
               ' -F "meta={meta}"'
               ' -H  "accept: application/json" -H  "Content-Type: multipart/form-data" '
               ' -F "sd_card_json=@{sd_speed}" -F "latencies_bag=@{latencies_bag}" '
               ' -F "meta_json=@{meta_json}"').format(
                    api_url= self.api_url,
                    id= diagnostics_id,
                    sd_speed='sd_speed.json',
                    latencies_bag='/mnt/{}.bag'.format(latencies_bag_name),
                    meta=res,
                    meta_json='meta.json',
               )
        self.ssh.command(cmd)

    def _do_diagnostics(self, latencies_bag_name, meta):
        """starts the diagnostics"""

        cmd = ('docker -H {botname}.local run -it --rm --net=host -v /var/run/docker.sock:/var/run/docker.sock '
                '-e LOG_API_PROTOCOL=https -e LOG_API_HOSTNAME=dashboard.duckietown.org -e LOG_API_VERSION=1.0 '
                '-e LOG_NOTES="{notes}" --name dts-run-diagnostics-system-monitor duckietown/dt-system-monitor:daffy-arm32v7 -- '
                '--target unix:///var/run/docker.sock --type duckiebot --app-id {app_id} '
                '--app-secret {app_secret} --database db_log_default --filter '
                '--group {group} --subgroup {subgroup} --duration {duration}').format(
                    botname=self.botname,
                    notes="called directly, not via dts",
                    group=self.bm_group,
                    subgroup=self.bm_subgroup,
                    duration=self.duration,
                    app_id=APP_ID,
                    app_secret=APP_SECRET)
        
        diagnostic_id = ""
        log_regex = r'v1__{}__{}__{}__\d*'.format(self.bm_group, self.bm_subgroup, self.botname)

        def update_id(line): 
            global diagnostic_id
            diagnostic_id = re.findall(log_regex, line)[0]
            print(diagnostic_id)

        command(cmd, 
                regex=[r'Log ID:\s+' + log_regex, r'\[system-monitor 00h:00m:[3-5]\ds\]', r'\[system-monitor 00h:01m:[2-5]\ds\]'], 
                callback=[update_id, lambda _: self._start_lane_following(), lambda _: self._record_bags(latencies_bag_name, meta['release'])], 
                onlyOnce=[True, True, True])
        return diagnostic_id
                
    def run(self):
        """starts the whole benchmark in correct order"""
        #meta = self._collect_meta()
        meta = {'release':  'master19'}
        in_cmd = 'dts --set-version {}'.format(meta['release'])
        demo_cmd = 'dts duckiebot demo --demo_name base --duckiebot_name {}'.format(self.botname)
        out_cmd = 'dts --set-version daffy'
        input("\n\nPrepare the setup by using the command in a separate terminal:\n\t$ {}\n\t$ {}\n\t$ {}\n\n\
        enter exit and THEN Press Enter to continue...".format(in_cmd, demo_cmd, out_cmd))
        latencies_bag_name = uuid.uuid1()
        #self._sync_time()
        self._do_pre_bm()
        start_cmd = 'dts duckiebot keyboard_control {}'.format(self.botname)
        input("\n\nPrepare an open keyboard-control using the command in a separate terminal:\n\t$ {}\n\nTHEN Press Enter to continue...".format(start_cmd))
        id = self._do_diagnostics(latencies_bag_name, meta)
        id = "v1__atags3__python3__watchtower01__1584492001"
        self._upload_to_api(id, latencies_bag_name, meta)
