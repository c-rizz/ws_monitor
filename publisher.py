#!/usr/bin/env python

import time
import argparse
import zmq
import json
import pynvml
import socket

pynvml.nvmlInit()
def get_gpus_infos():
    deviceCount = pynvml.nvmlDeviceGetCount()
    gpu_infos = {}
    for i in range(deviceCount):
        handle = pynvml.nvmlDeviceGetHandleByIndex(i)
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        gpu_infos[str(i)] = {   "name" : pynvml.nvmlDeviceGetName(handle),
                                "memory_size_bytes" : mem.total,
                                "stats" : { "gpu_proc_utilization_rate" : util.gpu,
                                            "gpu_mem_util" : util.memory,
                                            "gpu_mem_fill_rate" : 1-mem.free/mem.total}}
    return gpu_infos

def get_cpu_infos():
    return {    "cpu_utilization_rate" : float("nan"),
                "cpu_mem_fill_rate" : float("nan")}

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="tcp://127.0.0.1:8142", type=str, help="Address of the aggregator server.")
    ap.set_defaults(feature=True)
    args = vars(ap.parse_args())
    bind_to = args["server"]

    system_state_topic = b'system_stats'
    pub_period_sec = 1.0
    ctx = zmq.Context()
    s = ctx.socket(zmq.PUB)
    s.bind(bind_to)

    print(f"Starting broadcast on topic '{system_state_topic}'")
    time.sleep(1.0)

    while True:
        try:
            data = {}
            data["hostname"] = socket.gethostname()
            data["gpu"] = get_gpus_infos()
            data["cpu"] = get_cpu_infos()

            msg = json.dumps(data)
            s.send_multipart([system_state_topic, msg.encode("utf8")])
            # short wait so we don't hog the cpu
            time.sleep(pub_period_sec)
        except KeyboardInterrupt:
            print(f"Received SIGINT")
            break

    print("Waiting for message queues to flush...")
    time.sleep(0.5)
    print("Exiting")


if __name__ == "__main__":
    main()