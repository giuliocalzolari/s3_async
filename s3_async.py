#!/usr/bin/env python
# If not standard should be in requirements.txt
import yaml
import time
import os
import fnmatch
from cli.log import LoggingApp
from stat import S_ISDIR
import StringIO
import subprocess, threading
import Queue
import commands

import schedule
from pprint import pprint

import boto
import boto.utils
import boto.ec2
from boto.s3.key import Key

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


__author__ = ['Giulio.Calzolari']


 
 


class ChangeHandler(FileSystemEventHandler):

    def __init__(self, config, ec2, log):
        self.config = config
        self.log = log
        self.ec2_auto = ec2
        self.refresh = False
        self.copying = False
        self.last_access = time.time()
        self.queue_to_nofity = {}
        self.queue_thread_nofity = []


    def replicate_action(self):
        # replication with S3
        for repl in self.config["replicator"]:
            if self.config["replicator"][repl]["status"] != "enable":
                continue

            if len(self.config["replicator"][repl]["url"]) > 0:
                self.current_repl = self.config["replicator"][repl]
                if self.execute_sync():
                    self.copying = False


    def execute_sync(self):

        key_file = self.config["basedir"]+"/.aws_".self.current_repl["bucket"].".key"

        if not os.path.isfile(key_file): 
            f = open(key_file,'w+')
            f.write("[default]")
            f.write("accessKeyId:"+  self.current_repl["aws_access_key_id"]+"\n")
            f.write("secretKey:"+  self.current_repl["aws_secret_access_key"]+"\n")
            f.write("region:"+  self.current_repl["region"]+"\n")
            f.close()

        os.environ["AWS_CONFIG_FILE"] = key_file

        cmd = "aws s3 sync s3://"+self.current_repl["bucket"]+" "+self.config["basedir"] +" --quiet --region "+self.current_repl["region"]
        command_run = subprocess.call([cmd], shell=True)
        if command_run != 0:
            self.log.error("error on : " + cmd )
            return False
        else:
            self.log.debug("success on : " + cmd )
            return True


    def notify(self):
        t = threading.Thread(target=self.notify_exec, args=(self.current_notif,))
        t.start()
        self.queue_thread_nofity.append(t)

    def notify_exec(self,cfg):
        cmd = "echo 'refresh' | ssh  -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -o PasswordAuthentication=no -o ConnectTimeout=5 -o ConnectionAttempts=1 "+cfg["username"]+"@"+cfg["url"]+" -p "+str(cfg["port"])+" -i "+cfg["private_key"]+" 'cat > /tmp/.notify'"
        command_run = subprocess.call([cmd ], shell=True)
        if command_run != 0:
            self.log.error("error to notify : " + cfg["url"] )
            #  increment attempt
            if 'attempt' in cfg:
                cfg["attempt"] = cfg["attempt"] + 1 

                if cfg["attempt"] > self.config["max_retry"]:
                    del self.queue_to_nofity[cfg["url"]]
                    self.log.error("Impossible to notify : " + cfg["url"] )
                    return
            else:
                cfg["attempt"] = 1

            self.queue_to_nofity[cfg["url"]] = cfg

        else:
            self.log.debug("success notify : " + cfg["url"] )
            if cfg["url"] in self.queue_to_nofity:
                del self.queue_to_nofity[cfg["url"]]
                


    def wait_to_notify(self):
        if self.refresh == False:
            # self.log.debug("Nothing to do")
            return

        t1 = time.time()
        if (t1 - self.last_access) > self.config["grace_period"]:
            

            self.log.debug("Pass "+str(self.config["grace_period"])+" second from last change")

            self.copying = True
            self.replicate_action()
            
            #  fetch notificator
            for notif in self.config["notificator"]:
                if self.config["notificator"][notif]["status"] != "enable":
                    continue

                self.current_notif = self.config["notificator"][notif]

                # notify  static instances
                if not self.config["notificator"][notif]["url"].startswith('ec2://'):
                    self.notify()


                # notify  autodiscoverd instances
                if self.config["notificator"][notif]["url"].startswith('ec2://'):
                    for ec2_id, ec2_ip in self.ec2_auto.iteritems():
                        self.current_notif["url"] = ec2_ip
                        self.notify()


            self.refresh = False
            
            # wait for all threads to finish
            if self.queue_thread_nofity:
                for t in self.queue_thread_nofity:
                    t.join()

            

            self.re_nofity()
            schedule.every(self.config["retry_notify"]).seconds.do(self.re_nofity)


        else:
            self.log.debug("I'm waiting "+str(self.config["grace_period"] - int(t1 - self.last_access))+" to notify")


    def re_nofity(self):
        # list to reexecute
        
        if (len(self.queue_to_nofity) > 0 ):


            self.log.info("List to re-execute:"+str(len(self.queue_to_nofity)))
            for notif, cfg in self.queue_to_nofity.iteritems():
                self.log.debug("re_nofity:"+cfg["url"])
                self.current_notif = cfg
                self.notify()

            # wait for all threads to finish
            if self.queue_thread_nofity:
                for t in self.queue_thread_nofity:
                    t.join()
        else:
            self.log.debug("List to re-execute empty")
            schedule.cancel_job(self.re_nofity)


        
    

    def on_any_event(self, event):
        "If any file or folder is changed"

        if event.src_path == '/tmp/.notify':
            self.log.debug("Update request ")
            self.copying = True
            self.replicate_action()
            return

        # to avoid update loop on tmp
        if event.src_path.startswith('/tmp/'):
            return

        # to avoid update loop
        if self.copying:
            return

        self.refresh = True
        self.last_access = time.time()



        if event.is_directory:
            self.log.debug(
                "DIR : " + event.src_path + " " + event.event_type + " ")
        else:
            self.log.debug(
                "FILE: " + event.src_path + " " + event.event_type + " ")


class S3aSync(LoggingApp):

    def get_config(self):
        try:
            self.last_load = os.path.getmtime(self.params.config)
            self.config = yaml.load(open(self.params.config))
        except IOError as e:
            self.log.debug(e)
            quit("No Configuration file found at " + self.params.config)

    def execute_cmd(self, cmd):
        command_run = subprocess.call([cmd], shell=True)
        if command_run != 0:
            self.log.error("error on execute_cmd: " + cmd)
        else:
            self.log.debug("success on execute_cmd: " + cmd)


    def ec2_update_discovery(self, repl):
        self.log.info("get all instances match: " + repl["match_ec2"])

        idx = boto.utils.get_instance_metadata()['instance-id']
        if idx != "":
            self.log.debug("I am a ec2 instaces with id : " + idx)

        self.ec2_auto = {}
        ec2_conn = boto.ec2.connect_to_region(repl["region"],aws_access_key_id=repl["acces_key"],aws_secret_access_key=repl["secret_key"])
        reservations = ec2_conn.get_all_instances()
        instances = [i for r in reservations for i in r.instances]
        for i in instances:
            # pprint(i.__dict__)

            if idx == i.id:
                self.log.debug("skip myslef on ec2_update_discovery : " + idx)
                continue


            if fnmatch.fnmatch(i.tags["Name"], repl["match_ec2"]):

                if not str(i._state).startswith("running"):
                    self.log.debug("skip not running instances : "+ i.tags["Name"] +" - "+ i.id)
                    continue

                self.log.info("found new instances: " + i.tags["Name"])
                if repl["mapping"] == "public_ip_address":
                    self.ec2_auto[i.id] = i.ip_address or ""
                if repl["mapping"] == "private_ip_address":
                    self.ec2_auto[i.id] = i.private_ip_address or ""
                if repl["mapping"] == "public_dns_name":
                    self.ec2_auto[i.id] = i.public_dns_name or ""
                if repl["mapping"] == "public_dns_name":
                    self.ec2_auto[i.id] = i.private_dns_name or ""

        f = open(os.path.dirname(os.path.abspath(self.params.config))+"/autodiscovery.txt",'w+')
        for ec2_id, ec2_ip in self.ec2_auto.iteritems():
            f.write(ec2_id+":"+  ec2_ip+"\n")
        f.close()


    def ec2_autodiscovery(self):



        for notif in self.config["notificator"]:
           
            if self.config["notificator"][notif]["status"] != "enable":
                continue


            c_url =  self.config["notificator"][notif]["url"]
            if c_url.startswith('ec2://'):
                # autodiscovery polling
                self.ec2_update_discovery(self.config["notificator"][notif])
                interval = self.config["notificator"][notif]["refresh"]
                schedule.every(interval).seconds.do(self.ec2_update_discovery, self.config["notificator"][notif])





# ===========================MAIN===========================#

    def main(self):
        self.log.info("Starting")
        self.get_config()
        self.log.debug("directory Selected: " + self.config["basedir"])

        self.ec2_auto = {}
        # self.config_scheduled_cmd()
        self.ec2_autodiscovery()

        while 1:

            event_handler = ChangeHandler(self.config, self.ec2_auto, self.log)
            observer = Observer()
            _track = Observer()
            observer.schedule(event_handler, self.config["basedir"], recursive=True)
            _track.schedule(event_handler, "/tmp/", recursive=True)
            observer.start()
            _track.start()
            try:
                while True:

                    if os.path.getmtime(self.params.config) != self.last_load:
                        self.log.info("Config change reloading data")
                        self.get_config()

                        self.ec2_autodiscovery()

                        schedule.clear()
                        # self.config_scheduled_cmd()

                    time.sleep(1)
                    schedule.run_pending()
                    event_handler.wait_to_notify()

            except KeyboardInterrupt:
                quit("Exit")
                observer.stop()
                _track.stop()
        observer.join()
        _track.join()
        self.log.debug("Finished")


# ===========================MAGIC==============================#

if __name__ == "__main__":
    app = S3aSync()
    # app.add_param("-f", "--farm", help="Which vSphere you want to connect to in your config", default=None, required=True, action="store")
    # app.add_param("-m", "--mode", help="What to make foreman do. Excepted Values: ['index','create','command','script','snapshot','powercycle','filedrop',todo']", default=None, required=True, action="store")
    app.add_param("-c", "--config", help="Change the Configuration file to use",
                 default="./config.yaml", required=False, action="store")
    app.run()
