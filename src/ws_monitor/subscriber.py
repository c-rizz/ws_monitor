#!/usr/bin/env python

import zmq
import argparse
import threading
import json
import yaml
import time
import os
import numpy as np
import datetime
import pickle

def strike(text):
    result = ''
    for c in text:
        result = result + c + '\u0336'
    return result

class UsageStats:
    def __init__(self, filepath : str, wsname : str):
        # self._weekly_minute_activity = np.zeros(60*24*7, dtype = np.bool8) # For each minute a flag for when the computer was active
        # self._weekly_minute_monitored    = np.zeros(60*24*7, dtype = np.bool8) # For each minute a flag for when the computer was being monitored
        self._wsname = wsname
        self._yearly_minute_activity = np.zeros(60*24*366, dtype = bool) # For each minute a flag for when the computer was active
        self._yearly_minute_monitored    = np.zeros(60*24*366, dtype = bool) # For each minute a flag for when the computer was being monitored
        self._yearly_minute_active_users = np.zeros(60*24*366, dtype = np.uint16) # Active users for each minute (mask)

        self._users : dict[str,int] = {}

        filepath = filepath+".npz" if not filepath.endswith(".npz") else filepath
        self._filepath = filepath
        self._last_save = 0
        self._last_save_minute = 0
        self._save_freq_sec = 60
        self._load()

    def get_timestamp_idx(self, t : float):
        dt = datetime.datetime.fromtimestamp(t)
        return int((t-datetime.datetime.fromisoformat(f"{dt.year}-01-01").timestamp())/60)
    
    def get_datetime_idx(self, t : datetime.datetime):        
        return int((t.timestamp()-datetime.datetime.fromisoformat(f"{t.year}-01-01").timestamp())/60)

    def update(self, is_active : bool, active_users : list[str] = []):
        dt = datetime.datetime.now()
        idx_minute = self.get_datetime_idx(dt)
        # print(f"{self._wsname}: usage update")
        if idx_minute == self._last_save_minute:
            return
        for u in active_users:
            if u not in self._users:
                self._users[u] = len(self._users)
        active_user_ids = [self._users[u] for u in active_users]
        self._last_save_minute = idx_minute

        minute_from_year_start = idx_minute
        self._yearly_minute_activity[minute_from_year_start] = is_active
        self._yearly_minute_monitored[minute_from_year_start] = 1
        self._yearly_minute_active_users[minute_from_year_start] = sum([1 << idx for idx in active_user_ids if idx < 16])
        # print(f"{self._wsname}: usage update logging, is_active = {is_active}, at idx {minute_from_year_start}")

        # minute_from_week_start = dt.weekday()*24*60 + dt.hour*60 + dt.minute
        # self._weekly_minute_activity[minute_from_week_start] = is_active
        # self._weekly_minute_monitored[minute_from_week_start] = 1

        if time.monotonic() - self._last_save > 60:
            self._save()


    def _save(self):
        os.makedirs(os.path.dirname(self._filepath), exist_ok=True)
        tmpfile = self._filepath+".tmp.pkl"
        # np.savez(tmpfile,
        #          yearly_act = self._yearly_minute_activity,
        #          yearly_mon = self._yearly_minute_monitored,
        #          yearly_users = self._yearly_minute_active_users,
        #          users = self._users
        #          )
        with open(tmpfile,"wb") as f:
            pickle.dump(dict(yearly_act = self._yearly_minute_activity,
                                yearly_mon = self._yearly_minute_monitored,
                                yearly_users = self._yearly_minute_active_users,
                                users = self._users),
                        file=f)
        os.replace(tmpfile, self._filepath)
        self._last_save = time.monotonic()

    def _load(self):
        try:
            # d = np.load(self._filepath, allow_pickle=True)
            with open(self._filepath,"rb") as f:
                d = pickle.load(f)
            # if "weekly_act" in d:
            #     self._weekly_minute_activity = d["weekly_act"]
            # if "weekly_mon" in d:
            #     self._weekly_minute_monitored = d["weekly_mon"]
            self._yearly_minute_activity = d["yearly_act"]
            self._yearly_minute_monitored = d["yearly_mon"]
            self._yearly_minute_active_users = d["yearly_users"]
            self._users = d["users"]
            print(f"{self._wsname}: loaded activity from file")
        except OSError as e:
            print(f"could not open file {self._filepath}, will be created")
            pass

    def get_week_image(self):
        dt = datetime.datetime.now()
        # time_from_year_start = t-datetime.datetime.fromisoformat(f"{dt.year}-01-01").timestamp()
        # minute_from_year_start = int(time_from_year_start/60)
        
        weekstart_dt = datetime.datetime.combine(dt.date()-datetime.timedelta(days=6), datetime.datetime.min.time())
        weekstart_idx = self.get_datetime_idx(weekstart_dt)
        weekend_idx = weekstart_idx+7*24*60
        week_activity   = self._yearly_minute_activity[weekstart_idx:weekend_idx]
        week_monitoring = self._yearly_minute_monitored[weekstart_idx:weekend_idx]
        # print(f"weekstart_dt = {weekstart_dt}")
        # print(f"isodate = {isodate}")
        # print(f"_yearly_minute_activity.shape = {self._yearly_minute_activity.shape}")
        # print(f"plotting from = {weekstart_idx} to {weekend_idx}")
        # print(f"week_activity.shape = {week_activity.shape}")
        # print(f"week active minutes = {np.count_nonzero(week_activity)}")
        # print(f"week monitored minutes = {np.count_nonzero(week_activity)}")
        img = np.ones(shape=week_activity.shape+(3,), dtype=np.uint8)
        img *= 255
        img[week_activity]     = np.array([17, 17, 240]) # red
        img[np.logical_not(week_activity)] = np.array([56, 235, 56])  # green
        img[np.logical_not(week_monitoring)] = np.array([230, 226, 225])  # almost white

        img = img.reshape(7,24*60,3)
        r  = 40
        img = np.repeat(img, repeats=r, axis=0)
        # img = np.tile(img, r).reshape(r*7,24*60,3)
        for i in range(0,img.shape[0],r):
            border = [189, 172, 164]
            img[i] = np.array(border)  # gray
            img[i+r-1] = np.array(border)  # gray
        return img
    
    def get_week_recap(self):
        dt = datetime.datetime.now()
        # time_from_year_start = t-datetime.datetime.fromisoformat(f"{dt.year}-01-01").timestamp()
        # minute_from_year_start = int(time_from_year_start/60)
        
        weekstart_dt = datetime.datetime.combine(dt.date()-datetime.timedelta(days=6), datetime.datetime.min.time())
        weekstart_idx = self.get_datetime_idx(weekstart_dt)
        weekend_idx = weekstart_idx+7*24*60
        week_activity   = self._yearly_minute_activity[weekstart_idx:weekend_idx]
        week_monitoring = self._yearly_minute_monitored[weekstart_idx:weekend_idx]
        week_users = self._yearly_minute_active_users[weekstart_idx:weekend_idx]

        ret_strs = []
        for day in range(7):
            day_minutes = 60*24
            monitored_minutes = np.count_nonzero(week_monitoring[day*60*24:(day+1)*60*24])
            active_minutes =    np.count_nonzero(week_activity[day*60*24:(day+1)*60*24])
            day_users = week_users[day*60*24:(day+1)*60*24]
            monitored_ratio = monitored_minutes/day_minutes
            active_ratio = active_minutes/monitored_minutes if monitored_minutes>0 else float("nan")
            minutes_by_user = {}
            for name,idx in self._users.items():
                minutes_by_user[name] = np.count_nonzero(np.logical_and(day_users, 1<<idx))
            minutes_by_user_ratio = {n:m/monitored_minutes if monitored_minutes>0 else float("nan") for n,m in minutes_by_user.items()}
            daystr =  f"{(weekstart_dt + datetime.timedelta(days=day)).date()}: activity {active_ratio*100:2.0f}% monitored {monitored_ratio*100:2.0f}%\n"
            daystr += f"            "+(",".join(f"{n}:{r*100:2.0f}%" for n,r in minutes_by_user_ratio.items()))
            ret_strs.append(daystr)
        
        return "\n".join(ret_strs)
        



    



class WorkstationStatus:
    def __init__(self, hostname: str,
                 data_folder : str):
        self.hostname = hostname
        self._last_hour_activities = [0]*3600
        self._last_hour_activities_pos = 0
        self._last_activity_update = time.monotonic()
        self._last_active_time = 0
        self._last_inactive_time = time.monotonic()
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
        self._usage_stats = UsageStats(data_folder+"/full_stats.npy", wsname=self.hostname)

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
        curr_time = time.monotonic()
        time_since_update = curr_time - self._last_activity_update
        if active:
            self._last_active_time = curr_time
        else:
            self._last_inactive_time = curr_time
        active_in_last_minute = curr_time - self._last_active_time < 60 # less than 60 seconds since last activity
        if time_since_update >= 1:
            self._monitored_secs += 1
            if active_in_last_minute:
                self._active_secs += 1
        while time_since_update >= 1:
            prev = self._last_hour_activities[self._last_hour_activities_pos]
            self._last_hour_activities[self._last_hour_activities_pos]=active
            self._last_hour_activities_pos = (self._last_hour_activities_pos + 1) % len(self._last_hour_activities)
            self.activity_seconds += active - prev
            self.activity_len = min(self.activity_len+1,len(self._last_hour_activities))
            time_since_update -= 1
        self._usage_stats.update(active_in_last_minute, active_users=self.active_users)
    
    def get_active_users(self):
        active_users = set()
        gpus = self.data["gpu"]
        for gpu in gpus.values():
            for user, vram_ratio in gpu["memratio_by_user"].items():
                if vram_ratio > 0.05:
                    active_users.add(user)
        cpu_stats = self.data["cpu"]
        for user, ram_ratio in cpu_stats["memratio_by_user"].items():
            if ram_ratio > 0.3:
                active_users.add(user)
        return list(active_users)
    
    def activity_ratio(self):
        if self._monitored_secs == 0:
            return 0.0
        return self._active_secs / self._monitored_secs
    
    def get_week_image(self):
        return self._usage_stats.get_week_image()

    def get_week_recap(self):
        return self._usage_stats.get_week_recap()
    

class Subscriber():
    def __init__(self,  server : str = "tcp://*:9452",
                        data_folder : str = "./data"):
        self.data_rlock = threading.RLock()
        self.stats : dict[str,WorkstationStatus] = {}
        self._server_url = server
        self.data_folder = data_folder
        print(f"Using folder {os.path.abspath(data_folder)}")
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

    def get_ws_names(self):
        return [name for name in self.stats.keys()]

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
                                    f" l:{ws_status.activity_ratio()*100:.1f}%", 
                                    f" active_users:{all_stats['active_users']}", 
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

    def get_activity_img(self, ws_name):
        if ws_name in self.stats:
            return self.stats[ws_name].get_week_image()
        else:
            return None
        
    def get_activity_text(self, ws_name):
        if ws_name in self.stats:
            return self.stats[ws_name].get_week_recap()
        else:
            return None

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
