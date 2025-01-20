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

def get_stats_recap():
    with all_data_rlock:
        systems = sorted(all_data.keys())
        s = ""
        for sys in systems:
            try:
                data = all_data[sys]
                gpus = data["gpu"]
                top_vram_users = ""
                for gpu in gpus.values():
                    top_vram_user = max(gpu["memratio_by_user"].items(), key=lambda user_ratio: user_ratio[1])
                    top_vram_users += top_vram_user[0]+f" {top_vram_user[1]*100:.1f}%"
                cpu_stats = data["cpu"]
                top_mem_user = max(cpu_stats["memratio_by_user"].items(), key=lambda user_ratio: user_ratio[1])
                top_mem_user_str = top_mem_user[0]+f" {top_mem_user[1]*100:.1f}%"
                spacing = 10
                s +=    (   f"{data['hostname']}".ljust(spacing) +
                            f" CPU:{cpu_stats['cpu_utilization_ratio']*100:.2f}% \t".ljust(spacing) +
                            f" RAM:{cpu_stats['cpu_mem_fill_ratio']*100:.2f}% \t".ljust(spacing) +
                            (f" GPU:"+str([f"{gpu['stats']['gpu_proc_utilization_ratio']:.2f}%" for gpu in gpus.values()])+" \t").ljust(spacing) +
                            (f" VRAM:"+str([f"{gpu['stats']['gpu_mem_fill_ratio']*100:.2f}%" for gpu in gpus.values()])).ljust(spacing)+
                            (f" top_mem_user:"+str(top_mem_user_str).ljust(20))+
                            (f" top_vram_users:"+str(top_vram_users).ljust(15))+
                            "\n")
            except:
                s = f"{data['hostname']}: ERROR interpreting data."
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