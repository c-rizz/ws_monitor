#!/usr/bin/env python

import zmq
import argparse
import threading
import json
# import yaml
import time

def strike(text):
    result = ''
    for c in text:
        result = result + c + '\u0336'
    return result

class Subscriber():
    def __init__(self, server : str = "tcp://*:9452"):
        self.all_data_rlock = threading.RLock()
        self.all_data = {}
        self._server = server

        print(f"Listening on '{server}'")
        worker = threading.Thread(  target = self.receiver_worker,
                                    kwargs = { "bind_to" : self._server})
        worker.start()

    def update_stats(self, data : dict):
        with self.all_data_rlock:
            data["last_contact"] = time.time()
            self.all_data[data["hostname"]] = data

    def get_active_users(self, sys_stats):
        active_users = set()
        gpus = sys_stats["gpu"]
        for gpu in gpus.values():
            for user, vram_ratio in gpu["memratio_by_user"].items():
                if vram_ratio > 0.05:
                    active_users.add(user)
        cpu_stats = sys_stats["cpu"]
        for user, ram_ratio in cpu_stats["memratio_by_user"].items():
            if ram_ratio > 0.1:
                active_users.add(user)
        return list(active_users)
        

    def get_stats_recap(self):
        with self.all_data_rlock:
            systems = sorted(self.all_data.keys())
            s = ""
            lines = []
            for sys in systems:
                try:
                    data = self.all_data[sys]
                    age = time.time()-data['last_contact']
                    gpus = data["gpu"]
                    top_vram_users = ""
                    for gpu in gpus.values():
                        top_vram_user = max(gpu["memratio_by_user"].items(), key=lambda user_ratio: user_ratio[1]) if len(gpu["memratio_by_user"])>0 else ("None",0.0)
                        top_vram_users += top_vram_user[0]+f" {top_vram_user[1]*100:.1f}%"
                    cpu_stats = data["cpu"]
                    disk = data["disk"]
                    top_mem_user = max(cpu_stats["memratio_by_user"].items(), key=lambda user_ratio: user_ratio[1])
                    top_mem_user_str = top_mem_user[0]+f" {top_mem_user[1]*100:.1f}%"
                    lines.append(    ([f"{data['hostname']}[{age:.1f}s]",
                                        f" CPU:{cpu_stats['cpu_utilization_ratio']*100:.2f}% ",
                                        f" RAM:{cpu_stats['cpu_mem_fill_ratio']*100:.2f}% ",
                                        f" GPU:"+str([f"{gpu['stats']['gpu_proc_utilization_ratio']:.2f}%" for gpu in gpus.values()]),
                                        f" VRAM:"+str([f"{gpu['stats']['gpu_mem_fill_ratio']*100:.2f}%" for gpu in gpus.values()]),
                                        f" disk:"+str([f"{disk['stats']['disk_usage_ratio']*100:.2f}%" for gpu in gpus.values()]),
                                        f" top_mem_user:"+str(top_mem_user_str),
                                        f" top_vram_users:"+str(top_vram_users),
                                        f" active_users:"+str(self.get_active_users(data))], age, False))
                except Exception as e:
                    try:
                        data = self.all_data[sys]
                        age = time.time()-data['last_contact']
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
    ap.set_defaults(feature=True)
    args = vars(ap.parse_args())

    sub = Subscriber(args["server"])
    while True:
        print(sub.get_stats_recap())
        time.sleep(1)


if __name__ == "__main__":
    main()
