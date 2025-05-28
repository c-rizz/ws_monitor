#!/usr/bin/env python

import zmq
import argparse
import threading
import json
import yaml
import time
import os

def strike(text):
    result = ''
    for c in text:
        result = result + c + '\u0336'
    return result

class WorkstationStatus:
    def __init__(self, hostname: str,
                 data_folder : str):
        self.hostname = hostname
        self._last_hour_activities = [0]*3600
        self._last_hour_activities_pos = 0
        self._last_activity_update = time.monotonic()
        self.activity_seconds = 0
        self.activity_len = 0
        self._monitored_secs = 0
        self._active_secs = 0
        self._data_folder = data_folder
        self._stats_file = self._data_folder+"/stats.yaml"
        os.makedirs(self._data_folder, exist_ok=True)
        try:
            with open(self._stats_file) as f:
                conf = yaml.load(f, Loader=yaml.CLoader)
                self._monitored_secs = conf["monitored_secs"]
                self._active_secs = conf["active_secs"]
        except FileNotFoundError as e:
            print(f"could not open file {self._stats_file}, will be created")
            pass

    def _save_stats(self):
        with open(self._stats_file+".tmp", "w") as f:
            yaml.dump({"monitored_secs" : self._monitored_secs,
                       "active_secs" : self._active_secs}, f)
        os.replace(self._stats_file+".tmp", self._stats_file)

    def update_data(self, data):
        self.data = data
        self.last_contact = time.time()
        self.active_users = self.get_active_users()
        self._update_activity()
        self._save_stats()

    def _update_activity(self):
        active = 1 if len(self.active_users) > 0 else 0
        time_since_update = time.monotonic() - self._last_activity_update
        if time_since_update >= 1:
            self._monitored_secs += 1
            if active:
                self._active_secs += 1
        while time_since_update >= 1:
            prev = self._last_hour_activities[self._last_hour_activities_pos]
            self._last_hour_activities[self._last_hour_activities_pos]=active
            self._last_hour_activities_pos = (self._last_hour_activities_pos + 1) % len(self._last_hour_activities)
            self.activity_seconds += active - prev
            self.activity_len = min(self.activity_len+1,len(self._last_hour_activities))
            time_since_update -= 1
    
    def get_active_users(self):
        active_users = set()
        gpus = self.data["gpu"]
        for gpu in gpus.values():
            for user, vram_ratio in gpu["memratio_by_user"].items():
                if vram_ratio > 0.05:
                    active_users.add(user)
        cpu_stats = self.data["cpu"]
        for user, ram_ratio in cpu_stats["memratio_by_user"].items():
            if ram_ratio > 0.1:
                active_users.add(user)
        return list(active_users)
    
    def activity_ratio(self):
        if self._monitored_secs == 0:
            return 0.0
        return self._active_secs / self._monitored_secs
    

class Subscriber():
    def __init__(self,  server : str = "tcp://*:9452",
                        data_folder : str = "./data"):
        self.data_rlock = threading.RLock()
        self.stats : dict[str,WorkstationStatus] = {}
        self._server_url = server
        self.data_folder = data_folder
        print(f"Listening on '{server}'")
        worker = threading.Thread(  target = self.receiver_worker,
                                    kwargs = { "bind_to" : self._server_url})
        worker.start()

    def update_stats(self, data : dict):
        with self.data_rlock:
            if data["hostname"] not in self.stats:
                status = WorkstationStatus(data["hostname"],
                                           data_folder=self.data_folder+"/"+data["hostname"])
            else:
                status = self.stats[data["hostname"]]
            status.update_data(data)
            self.stats[data["hostname"]] = status

    def get_stats_recap(self):
        with self.data_rlock:
            systems = sorted(self.stats.keys())
            s = ""
            lines = []
            for sys in systems:
                try:
                    ws_status = self.stats[sys]
                    data = ws_status.data
                    age = time.time()-ws_status.last_contact
                    gpus = data["gpu"]
                    top_vram_users_str = ""
                    for gpu in gpus.values():
                        top_vram_user = max(gpu["memratio_by_user"].items(), key=lambda user_ratio: user_ratio[1]) if len(gpu["memratio_by_user"])>0 else ("None",0.0)
                        top_vram_users_str += top_vram_user[0]+f" {top_vram_user[1]*100:.1f}%"
                    cpu_stats = data["cpu"]
                    disk = data.get("disk",None)
                    if disk is not None:
                        disk_str = str([f"{disk['stats']['disk_usage_ratio']*100:.2f}%" for gpu in gpus.values()])
                    else:
                        disk_str = "N/A"
                    top_mem_user = max(cpu_stats["memratio_by_user"].items(), key=lambda user_ratio: user_ratio[1])
                    top_mem_user_str = top_mem_user[0]+f" {top_mem_user[1]*100:.1f}%"

                    all_stats = {"cpu_ut" : f"{cpu_stats['cpu_utilization_ratio']*100:.2f}%",
                                 "ram_ut" : f"{cpu_stats['cpu_mem_fill_ratio']*100:.2f}%",
                                 "gpus_ut" : str([f"{gpu['stats']['gpu_proc_utilization_ratio']:.2f}%" for gpu in gpus.values()]),
                                 "vrams_ut" : str([f"{gpu['stats']['gpu_mem_fill_ratio']*100:.2f}%" for gpu in gpus.values()]),
                                 "disk_ut" : disk_str,
                                 "top_mem_user" : top_mem_user_str,
                                 "top_vram_users" : top_vram_users_str,
                                 "active_users" : str(ws_status.active_users)}
                    if age > 300:
                        all_stats = {k:"???" for k in all_stats}

                    lines.append( ([f"{data['hostname']}[{age:.1f}s]",
                                    f" CPU:{all_stats['cpu_ut']} ",
                                    f" RAM:{all_stats['ram_ut']} ",
                                    f" GPU:{all_stats['gpus_ut']}",
                                    f" VRAM:{all_stats['vrams_ut']}",
                                    f" disk:{all_stats['disk_ut']}",
                                    f" top_mem_user:{all_stats['top_mem_user']}",
                                    f" top_vram_users:{all_stats['top_vram_users']}",
                                    f" active_users:{all_stats['active_users']}", 
                                    f" l:{ws_status.activity_ratio()*100:.1f}%", 
                                    # f" hourly:{ws_status.activity_seconds/ws_status.activity_len*100:.1f}%"
                                    ],
                                    age, 
                                    False))
                except Exception as e:
                    try:
                        age = time.time()-ws_status.last_contact
                    except Exception:
                        age = None
                    lines.append((f"{data['hostname']}: ERROR interpreting data. {e}\n", age, True))
            
            if len(lines)>0:
                cols = 0
                for line, age, raw in lines:
                    if isinstance(line, list):
                        cols = len(line)
                widths = [1]*cols
                for line, age, raw in lines:
                    if not raw:
                        for i,col in enumerate(line):
                            widths[i] = max(widths[i], len(col)+1)
                for line, age, raw in lines:
                    if not raw:
                        for i in range(len(line)):
                            line[i] = line[i].ljust(widths[i])
                for line, age, raw in lines:
                    if raw:
                        line_str = line
                    else:
                        line_str = "".join(line)+"\n"
                    #if age > 60:
                    #    line_str = strike(line_str)
                    s+= line_str
            
            return s

    def receiver_worker(self, bind_to : str):
        system_state_topic = b'system_stats'
        ctx = zmq.Context()
        s = ctx.socket(zmq.SUB)
        s.bind(bind_to)
        print(f"Listening on {bind_to}")

        s.setsockopt(zmq.SUBSCRIBE, system_state_topic)
        try:
            while True:
                topic, msg = s.recv_multipart()
                data = json.loads(msg)
                self.update_stats(data)
        except KeyboardInterrupt:
            pass

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="tcp://*:9452", type=str, help="Address of the aggregator server.")
    ap.add_argument("--data-folder", default="./data", type=str, help="Folder containing server data.")
    ap.set_defaults(feature=True)
    args = vars(ap.parse_args())

    sub = Subscriber(args["server"], args["data_folder"])
    while True:
        print(sub.get_stats_recap())
        time.sleep(1)


if __name__ == "__main__":
    main()
