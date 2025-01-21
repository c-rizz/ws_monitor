#!/usr/bin/env python

import zmq
import argparse
import threading
import json
# import yaml
import time

all_data_rlock = threading.RLock()
all_data = {}
def update_stats(data : dict):
    with all_data_rlock:
        all_data[data["hostname"]] = data

def get_active_users(sys_stats):
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
    

def get_stats_recap():
    with all_data_rlock:
        systems = sorted(all_data.keys())
        s = ""
        to_print = []
        to_print_raw = []
        for sys in systems:
            try:
                data = all_data[sys]
                gpus = data["gpu"]
                top_vram_users = ""
                for gpu in gpus.values():
                    top_vram_user = max(gpu["memratio_by_user"].items(), key=lambda user_ratio: user_ratio[1]) if len(gpu["memratio_by_user"])>0 else ("None",0.0)
                    top_vram_users += top_vram_user[0]+f" {top_vram_user[1]*100:.1f}%"
                cpu_stats = data["cpu"]
                top_mem_user = max(cpu_stats["memratio_by_user"].items(), key=lambda user_ratio: user_ratio[1])
                top_mem_user_str = top_mem_user[0]+f" {top_mem_user[1]*100:.1f}%"
                to_print.append(    [f"{data['hostname']}",
                                    f" CPU:{cpu_stats['cpu_utilization_ratio']*100:.2f}% ",
                                    f" RAM:{cpu_stats['cpu_mem_fill_ratio']*100:.2f}% ",
                                    f" GPU:"+str([f"{gpu['stats']['gpu_proc_utilization_ratio']:.2f}%" for gpu in gpus.values()]),
                                    f" VRAM:"+str([f"{gpu['stats']['gpu_mem_fill_ratio']*100:.2f}%" for gpu in gpus.values()]),
                                    f" top_mem_user:"+str(top_mem_user_str),
                                    f" top_vram_users:"+str(top_vram_users),
                                    f" active_users:"+str(get_active_users(data))])
            except Exception as e:
                to_print_raw.append(f"{data['hostname']}: ERROR interpreting data. {e}")
        
        if len(to_print)>0:
            widths = [1]*len(to_print[0])
            for line in to_print:
                for i,col in enumerate(line):
                    widths[i] = max(widths[i], len(col)+1)
            for line in to_print:
                for i in range(len(line)):
                    line[i] = line[i].ljust(widths[i])
                s+="".join(line)+"\n"
        for line in to_print_raw:
            s+=line+"\n"
        
        return s

def receiver_worker(bind_to : str):
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
            update_stats(data)
    except KeyboardInterrupt:
        pass

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="tcp://*:9452", type=str, help="Address of the aggregator server.")
    ap.set_defaults(feature=True)
    args = vars(ap.parse_args())

    worker = threading.Thread(  target = receiver_worker,
                                kwargs = { "bind_to" : args["server"]})
    worker.start()

    while True:
        print(get_stats_recap())
        time.sleep(1)


if __name__ == "__main__":
    main()