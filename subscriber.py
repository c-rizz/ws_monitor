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
            data = all_data[sys]
            gpus = data["gpu"]
            cpu_stats = data["cpu"]
            s +=    (   f"{data['hostname']} \t "
                        f" CPU:{cpu_stats['cpu_utilization_rate']*100:.2f}% \t"
                        f" RAM:{cpu_stats['cpu_mem_fill_rate']*100:.2f}% \t"
                        f" GPU:"+str([f"{gpu['stats']['gpu_proc_utilization_rate']:.2f}%" for gpu in gpus.values()])+" \t"
                        f" VRAM:"+str([f"{gpu['stats']['gpu_mem_fill_rate']*100:.2f}%" for gpu in gpus.values()])+" \t\n")
        return s

def receiver_worker(connect_to : str):
    system_state_topic = b'system_stats'
    ctx = zmq.Context()
    s = ctx.socket(zmq.SUB)
    s.connect(connect_to)

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
    ap.add_argument("--server", default="tcp://127.0.0.1:8142", type=str, help="Address of the aggregator server.")
    ap.set_defaults(feature=True)
    args = vars(ap.parse_args())
    connect_to = args["server"]

    worker = threading.Thread(  target = receiver_worker,
                                kwargs = { "connect_to" : connect_to})
    worker.start()

    while True:
        print(get_stats_recap())
        time.sleep(1)


if __name__ == "__main__":
    main()