#!/usr/bin/env python

import time
import argparse
import zmq
import json
import pynvml
import socket
import psutil
import subprocess
import re

pynvml.nvmlInit()
def get_gpus_infos():
    deviceCount = pynvml.nvmlDeviceGetCount()
    gpu_infos = {}
    for i in range(deviceCount):
        handle = pynvml.nvmlDeviceGetHandleByIndex(i)
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        procs = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
        user_mem_usageratio = {}
        for proc in procs:
            user = psutil.Process(proc.pid).username()
            if user not in user_mem_usageratio:
                user_mem_usageratio[user] = 0.0
            user_mem_usageratio[user] += proc.usedGpuMemory/mem.total
        print(f"user_mem_usageratio = {user_mem_usageratio}")
        gpu_infos[str(i)] = {   "name" : pynvml.nvmlDeviceGetName(handle),
                                "memory_size_bytes" : mem.total,
                                "stats" : { "gpu_proc_utilization_ratio" : util.gpu,
                                            "gpu_mem_util" : util.memory,
                                            "gpu_mem_fill_ratio" : 1-mem.free/mem.total,
                                            },
                                "memratio_by_user" : user_mem_usageratio}
    return gpu_infos

def get_memory_usage_by_user():
    out = subprocess.check_output("sudo smem -up -c \"user pss\" -s pss", shell=True).decode("utf-8")
    lines_user_pss = list(reversed([l.split() for l in out.splitlines()]))[:-1]
    print(f"{lines_user_pss}")
    user_pssratio = {l[0]: float(l[1][:-1])/100 for l in lines_user_pss}
    return user_pssratio

def get_cpu_infos():
    return {    "cpu_utilization_ratio" : psutil.virtual_memory().used / psutil.virtual_memory().total,
                "cpu_mem_fill_ratio" : psutil.cpu_percent()/100,
                "memratio_by_user" : get_memory_usage_by_user()}

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="tcp://127.0.0.1:9452", type=str, help="Address of the aggregator server.")
    ap.set_defaults(feature=True)
    args = vars(ap.parse_args())

    system_state_topic = b'system_stats'
    pub_period_sec = 1.0
    ctx = zmq.Context()
    s = ctx.socket(zmq.PUB)
    s.connect(args["server"])


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