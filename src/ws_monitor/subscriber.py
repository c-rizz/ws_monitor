#!/usr/bin/env python

import zmq
import argparse
import threading
import json
import logging
import yaml
import time
import os
import numpy as np
import datetime
import pickle
from typing import Any, Dict

logger = logging.getLogger(__name__)

def strike(text):
    result = ''
    for c in text:
        result = result + c + '\u0336'
    return result

def format_age(seconds: float) -> str:
    if seconds != seconds:  # nan
        return "nan"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = seconds/60
    if minutes < 60:
        return f"{minutes:.1f}m"
    hours = minutes/60
    if hours < 24:
        return f"{hours:.1f}h"
    days = hours/24
    return f"{days:.1f}d"

bright_green = np.array([56, 235, 56])
pastel_green = np.array((89, 220, 111))
bright_red   = np.array([17, 17, 240])
punch_red     = np.array((42, 42, 218))
light_gray   = np.array([240, 235, 245])
dark_gray    = np.array([189, 172, 164])
almost_white = np.array([230, 226, 225])

class UsageStats:
    _MINUTES_PER_YEAR_BUFFER = 60*24*366  # sized for leap years; the tail is simply unused otherwise

    def __init__(self, filepath : str, wsname : str):
        self._wsname = wsname
        # One set of arrays per calendar year, allocated lazily. Keeping years separate (rather
        # than one buffer reused every year) means a slot that's never been written this year is
        # unambiguously "not monitored" - no risk of showing last year's leftover data for a slot
        # the clock hasn't reached yet this year, and no special-casing needed for weeks that span
        # a Dec/Jan boundary since we just read from two years' buffers.
        self._years : dict[int, dict[str, np.ndarray]] = {}

        self._users : dict[str,int] = {}

        filepath = filepath+".npz" if not filepath.endswith(".npz") else filepath
        self._filepath = filepath
        self._last_save = 0
        self._last_save_minute = -1
        self._last_save_year = -1
        self._save_freq_sec = 60
        self._load()

    def get_timestamp_idx(self, t : float):
        dt = datetime.datetime.fromtimestamp(t)
        return int((t-datetime.datetime.fromisoformat(f"{dt.year}-01-01").timestamp())/60)

    def get_datetime_idx(self, t : datetime.datetime):
        return int((t.timestamp()-datetime.datetime.fromisoformat(f"{t.year}-01-01").timestamp())/60)

    def _get_year_arrays(self, year : int) -> dict[str, np.ndarray]:
        if year not in self._years:
            self._years[year] = {
                "act": np.zeros(self._MINUTES_PER_YEAR_BUFFER, dtype = bool),
                "mon": np.zeros(self._MINUTES_PER_YEAR_BUFFER, dtype = bool),
                "users": np.zeros(self._MINUTES_PER_YEAR_BUFFER, dtype = np.uint16),
            }
        return self._years[year]

    def _get_range(self, start_dt : datetime.datetime, end_dt : datetime.datetime):
        """Returns (activity, monitored, users) arrays covering [start_dt, end_dt), stitching
        across a calendar-year boundary if the range crosses one. Minutes in a year we have no
        data for (not yet monitored, or simply never allocated) come back as False/0."""
        total_minutes = int((end_dt - start_dt).total_seconds() // 60)
        activity = np.zeros(total_minutes, dtype=bool)
        monitored = np.zeros(total_minutes, dtype=bool)
        users = np.zeros(total_minutes, dtype=np.uint16)
        cursor = start_dt
        pos = 0
        while pos < total_minutes:
            year = cursor.year
            idx = self.get_datetime_idx(cursor)
            minutes_left_in_year = int((datetime.datetime(year+1,1,1) - cursor).total_seconds() // 60)
            take = min(minutes_left_in_year, total_minutes - pos)
            if year in self._years:
                arrs = self._years[year]
                activity[pos:pos+take] = arrs["act"][idx:idx+take]
                monitored[pos:pos+take] = arrs["mon"][idx:idx+take]
                users[pos:pos+take] = arrs["users"][idx:idx+take]
            pos += take
            cursor += datetime.timedelta(minutes=take)
        return activity, monitored, users

    def update(self, is_active : bool, active_users : list[str] = []):
        dt = datetime.datetime.now()
        idx_minute = self.get_datetime_idx(dt)
        # print(f"{self._wsname}: usage update")
        if idx_minute == self._last_save_minute and dt.year == self._last_save_year:
            return
        for u in active_users:
            if u not in self._users:
                self._users[u] = len(self._users)
        active_user_ids = [self._users[u] for u in active_users]
        self._last_save_minute = idx_minute
        self._last_save_year = dt.year

        arrs = self._get_year_arrays(dt.year)
        arrs["act"][idx_minute] = is_active
        arrs["mon"][idx_minute] = 1
        arrs["users"][idx_minute] = sum([1 << idx for idx in active_user_ids if idx < 16])
        # print(f"{self._wsname}: usage update logging, is_active = {is_active}, at idx {idx_minute} of {dt.year}")

        if time.monotonic() - self._last_save > 60:
            self._save()


    def _save(self):
        os.makedirs(os.path.dirname(self._filepath), exist_ok=True)
        tmpfile = self._filepath+".tmp.pkl"
        with open(tmpfile,"wb") as f:
            pickle.dump(dict(years = self._years,
                                users = self._users),
                        file=f)
        os.replace(tmpfile, self._filepath)
        self._last_save = time.monotonic()

    def _load(self):
        try:
            with open(self._filepath,"rb") as f:
                d = pickle.load(f)
            self._users = d.get("users", {})
            if "years" in d:
                self._years = d["years"]
            else:
                self._years = {}
                self._migrate_legacy_format(d)
            logger.info(f"{self._wsname}: loaded activity from file at {os.path.abspath(self._filepath)}")
        except OSError as e:
            logger.info(f"could not open file {self._filepath}, will be created")
            pass

    def _migrate_legacy_format(self, d : dict):
        """Splits data from the old single-fixed-buffer format (reused every year, with no year
        tag at all) into per-year buffers, using pure calendar position rather than any recorded
        epoch (an intermediate, now-abandoned fix briefly added one; it's ignored here and every
        legacy file is treated the same way regardless of whether it has that field).

        The split is fully deterministic: a slot holds whatever was *most recently* written to
        it, so the part of the buffer from Jan 1 up to right now was necessarily last written
        during the current pass through the year - i.e. it's genuinely this year's data. The
        remainder (later in the year, not reached yet) hasn't been touched since the previous
        pass through that same calendar position, so it must still hold last year's value."""
        old_act = d.get("yearly_act")
        old_mon = d.get("yearly_mon")
        old_users = d.get("yearly_users")
        if old_act is None:
            return
        now = datetime.datetime.now()
        now_idx = self.get_datetime_idx(now)

        this_year = self._get_year_arrays(now.year)
        this_year["act"][:now_idx+1] = old_act[:now_idx+1]
        this_year["mon"][:now_idx+1] = old_mon[:now_idx+1]
        this_year["users"][:now_idx+1] = old_users[:now_idx+1]

        last_year = self._get_year_arrays(now.year - 1)
        last_year["act"][now_idx+1:] = old_act[now_idx+1:]
        last_year["mon"][now_idx+1:] = old_mon[now_idx+1:]
        last_year["users"][now_idx+1:] = old_users[now_idx+1:]

        migrated_minutes = int(np.count_nonzero(old_mon))
        logger.info(f"{self._wsname}: migrated legacy usage history into {now.year} (elapsed part) "
                    f"and {now.year-1} (remainder) - {migrated_minutes} monitored minutes total")

    def get_week_image(self, start_date : datetime.date):
        # print(f"Generating week image for {self._wsname} starting at {start_date}")
        weekstart_dt = datetime.datetime.combine(start_date, datetime.datetime.min.time())
        weekend_dt = weekstart_dt + datetime.timedelta(days=7)
        week_activity, week_monitoring, _ = self._get_range(weekstart_dt, weekend_dt)
        img = np.ones(shape=week_activity.shape+(3,), dtype=np.uint8)
        img *= 255
        img[week_activity]     = punch_red
        img[np.logical_not(week_activity)] = pastel_green
        img[np.logical_not(week_monitoring)] = almost_white

        img = img.reshape(7,24*60,3)
        r  = 40
        img = np.repeat(img, repeats=r, axis=0)
        # img = np.tile(img, r).reshape(r*7,24*60,3)
        for i in range(0,img.shape[0],r):
            img[i] = dark_gray
            img[i+r-1] = dark_gray
        return img


    def get_week_users_images(self):
        dt = datetime.datetime.now()
        row_height = 20

        weekstart_dt = datetime.datetime.combine(dt.date()-datetime.timedelta(days=6), datetime.datetime.min.time())
        weekend_dt = weekstart_dt + datetime.timedelta(days=7)
        _, week_monitored, week_users = self._get_range(weekstart_dt, weekend_dt)

        img_mon = np.full(fill_value=255,shape=week_monitored.shape+(3,), dtype=np.uint8)
        img_mon[np.logical_not(week_monitored)] = light_gray

        user_images : dict[str,np.ndarray]= {}
        for uname,uid in self._users.items():
            logger.debug(f"{uname} : {uid}")
            week_user_active = np.bitwise_and(week_users, 1<<uid) != 0
            img_user = img_mon.copy()
            img_user[week_user_active] = punch_red
            img_user[np.logical_not(week_user_active)] = pastel_green
            img_user = img_user.reshape(7,24*60,3)
            img_user = np.repeat(img_user, repeats=row_height, axis=0)
            for i in range(0,img_user.shape[0],row_height):
                img_user[i] = dark_gray
                img_user[i+row_height-1] = dark_gray
            user_images[uname] = img_user

        return user_images



    def get_week_recap(self):
        dt = datetime.datetime.now()
        weekstart_dt = datetime.datetime.combine(dt.date()-datetime.timedelta(days=6), datetime.datetime.min.time())
        weekend_dt = weekstart_dt + datetime.timedelta(days=7)
        week_activity, week_monitoring, week_users = self._get_range(weekstart_dt, weekend_dt)

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
                minutes_by_user[name] = np.count_nonzero(np.bitwise_and(day_users, 1<<idx))
            minutes_by_user_ratio = {n:m/monitored_minutes if monitored_minutes>0 else float("nan") for n,m in minutes_by_user.items()}
            daystr =  f"{(weekstart_dt + datetime.timedelta(days=day)).date()}: active {active_ratio*100: 4.0f}% monitored {monitored_ratio*100: 4.0f}% \t"
            daystr += f"            "+(", ".join(f"{n}:{r*100: 4.0f}%" for n,r in minutes_by_user_ratio.items()))
            ret_strs.append(daystr)
        
        return "\n".join(ret_strs)

    def get_usage_minutes_per_user(self, from_datetime: datetime.datetime, to_datetime: datetime.datetime) -> dict[str, int]:
        """Return the per-user active minute counts for the last 7 days (inclusive)."""
        if from_datetime >= to_datetime:
            return {}

        _, _, week_users = self._get_range(from_datetime, to_datetime)
        minutes_by_user: dict[str, int] = {}
        for name, idx in self._users.items():
            if idx >= 16:
                # Minutes cannot be represented beyond the 16 tracked bit positions.
                minutes_by_user[name] = 0
                continue
            mask = 1 << idx
            active_minutes = int(np.count_nonzero(np.bitwise_and(week_users, mask)))
            minutes_by_user[name] = active_minutes
        return minutes_by_user

    def get_usage_ratio(self, start_datetime : datetime.datetime, end_datetime : datetime.datetime):
        if start_datetime >= end_datetime:
            return float("nan")
        # print(f"Calculating usage ratio from {start_datetime} to {end_datetime}")
        activity, monitored, _ = self._get_range(start_datetime, end_datetime)
        active_monitored = np.logical_and(activity, monitored)
        monitored_minutes = np.count_nonzero(monitored)
        active_monitored_minutes = np.count_nonzero(active_monitored)
        active_ratio = active_monitored_minutes/monitored_minutes if monitored_minutes>0 else float("nan")
        return active_ratio



    



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

        self._last_received_sessionid = float("-inf")
        self._last_received_seqnum = float("-inf")

        os.makedirs(self._data_folder, exist_ok=True)
        # Placeholder contact info, used verbatim until (if ever) update_data() is
        # called with real data. Lets a workstation we have saved data for but
        # haven't heard from this run still show up (as disconnected) in the recap,
        # instead of only appearing once it publishes again. See Subscriber._load_known_workstations.
        self.data: Dict[str, Any] = {"hostname": hostname}
        self.last_contact = 0.0
        try:
            with open(self._stats_file) as f:
                conf = yaml.safe_load(f)
                self._monitored_secs = conf["monitored_secs"]
                self._active_secs = conf["active_secs"]
            self.last_contact = os.path.getmtime(self._stats_file)
        except FileNotFoundError as e:
            logger.info(f"could not open file {self._stats_file}, will be created")
            pass
        self._usage_stats = UsageStats(data_folder+"/full_stats.npy", wsname=self.hostname)

    def _save_stats(self):
        with open(self._stats_file+".tmp", "w") as f:
            yaml.dump({"monitored_secs" : self._monitored_secs,
                       "active_secs" : self._active_secs}, f)
        os.replace(self._stats_file+".tmp", self._stats_file)

    def update_data(self, data):
        new_data_sessionid = data.get("session_id", None)
        new_data_seqnum = data.get("seq_num", None)
        if new_data_sessionid > self._last_received_sessionid:
            # new session, reset seqnum
            self._last_received_seqnum = float("-inf")
        is_old_session = new_data_sessionid is not None and self._last_received_sessionid is not None and new_data_sessionid < self._last_received_sessionid
        is_old_seqnum = new_data_seqnum is not None and self._last_received_seqnum is not None and new_data_seqnum <= self._last_received_seqnum
        if is_old_session or is_old_seqnum:
            logger.debug(f"Ignoring old data for {self.hostname}: session_id {new_data_sessionid} (last {self._last_received_sessionid}), seq_num {new_data_seqnum} (last {self._last_received_seqnum})")
            return self
        self._last_received_sessionid = new_data_sessionid
        self._last_received_seqnum = new_data_seqnum
        # print(f"Updating data for {self.hostname}: session_id {new_data_sessionid}, seq_num {new_data_seqnum}")

        self.data = data
        self.last_contact = time.time()
        self.active_users, self.users_top_proc_age = self.get_active_users()
        if not hasattr(self, 'active_users_in_last_minute'):
            self.active_users_in_last_minute_times = {}
        self.active_users_in_last_minute_times = {k:v for k,v in self.active_users_in_last_minute_times.items() if time.monotonic()-v < 60}
        self.active_users_in_last_minute_times.update({u:time.monotonic() for u in self.active_users})
        self.active_users_in_last_minute = list(self.active_users_in_last_minute_times.keys())
        self._update_activity()
        self._save_stats()
        return self

    def _update_activity(self):
        active = 1 if len(self.active_users) > 0 else 0
        curr_time = time.monotonic()
        time_since_update = curr_time - self._last_activity_update
        self._last_activity_update = curr_time
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
        users_top_proc_age = {}
        gpus = self.data["gpu"]
        for gpu in gpus.values():
            for user, vram_ratio in gpu["memratio_by_user"].items():
                tot_mem_bytes = gpu["memory_size_bytes"]
                mem_usage_bytes = {u:r*tot_mem_bytes for u,r in gpu["memratio_by_user"].items()}
                if vram_ratio > 0.1 or mem_usage_bytes.get(user, 0) > 1024**3:
                    active_users.add(user)
                    t = time.time()
                    if "top_users_proc" in gpu and user in gpu["top_users_proc"]:
                        top_proc_creation_time = gpu.get("top_users_proc", {}).get(user, {}).get("creation_time", t)
                        users_top_proc_age[user] = t - top_proc_creation_time
        cpu_stats = self.data["cpu"]
        for user, ram_ratio in cpu_stats["memratio_by_user"].items():
            if ram_ratio > 0.3 and ram_ratio < cpu_stats["cpu_mem_fill_ratio"]: # there's some bug in the user ram_ratio, exclude it if it doesn't make sense
                active_users.add(user)
        return list(active_users), users_top_proc_age
    
    def daily_activity_ratio(self):
        return self._usage_stats.get_usage_ratio(
            start_datetime = datetime.datetime.now()-datetime.timedelta(days=1),
            end_datetime = datetime.datetime.now()
        )
    
    def weekly_activity_ratio(self):
        return self._usage_stats.get_usage_ratio(
            start_datetime = datetime.datetime.now()-datetime.timedelta(weeks=1),
            end_datetime = datetime.datetime.now()
        )
    
    def activity_ratio(self,  since_seconds_ago: int):
        now = datetime.datetime.now()
        return self._usage_stats.get_usage_ratio(
            start_datetime = now - datetime.timedelta(seconds=since_seconds_ago),
            end_datetime = now
        )

    def usage_minutes_per_user(self, since_seconds_ago: int):
        now = datetime.datetime.now()
        return self._usage_stats.get_usage_minutes_per_user(
            from_datetime = now - datetime.timedelta(seconds=since_seconds_ago),
            to_datetime = now
        )

    def get_usage_stats(self):
        return self._usage_stats
    

class Subscriber():
    def __init__(self,  server : str = "tcp://*:9452",
                        data_folder : str = "./data",
                        user_alias_lookup: dict[str, str] | None = None,
                        autostart : bool = True):
        self._server_url = server
        self.data_folder = data_folder
        self._user_alias_lookup: dict[str, str] = user_alias_lookup or {}
        logger.info(f"Using folder {os.path.abspath(data_folder)}")
        logger.info(f"Listening on '{server}'")
        self.reload(autostart=autostart)

    def reload(self, autostart : bool = True):
        """Re-initializes in place: drops all in-memory state and reloads every known
        workstation fresh from disk, then (by default) restarts the ZMQ receiver.

        This exists so a long-lived caller can force a fresh read of current disk state
        without discarding this object and everyone's references to it - see web_page.py's
        post_fork, which calls this instead of constructing a new Subscriber and rebinding
        the module-level name, precisely because a freshly (re)spawned gunicorn worker
        needs its `app.subscriber` to reflect what's on disk now, not whatever it was at
        the time of the fork.

        Only meant to be called on an instance whose receiver isn't currently running
        (e.g. right after __init__ with autostart=False, or before any prior reload()) -
        it doesn't stop an already-running receiver thread first, so calling it while one
        is active would leave two threads racing to bind the same ZMQ socket.
        """
        self.data_rlock = threading.RLock()
        self.stats : dict[str,WorkstationStatus] = {}
        self._load_known_workstations()
        if autostart:
            self._start_receiver()

    def _load_known_workstations(self):
        """Pre-populate self.stats from previously-saved per-workstation data, so a
        workstation we have history for still shows up (as disconnected) right after
        a restart, instead of only reappearing once it publishes again."""
        if not os.path.isdir(self.data_folder):
            return
        for hostname in os.listdir(self.data_folder):
            ws_data_folder = os.path.join(self.data_folder, hostname)
            if not os.path.isdir(ws_data_folder):
                continue
            try:
                self.stats[hostname] = WorkstationStatus(hostname, data_folder=ws_data_folder)
            except Exception as e:
                logger.warning(f"Could not load saved data for workstation '{hostname}': {e}")

    def _start_receiver(self):
        worker = threading.Thread(  target = self.receiver_worker,
                                    kwargs = { "bind_to" : self._server_url},
                                    daemon = True)
        worker.start()

    def update_stats(self, data : dict):
        with self.data_rlock:
            if data["hostname"] not in self.stats:
                status = WorkstationStatus(data["hostname"],
                                           data_folder=self.data_folder+"/"+data["hostname"])
            else:
                status = self.stats[data["hostname"]]
            self.stats[data["hostname"]] = status.update_data(data)

    def get_ws_names(self):
        return [name for name in self.stats.keys()]

    def get_stats_recap(self):
        stats_list = self.get_stats_recap_dictlist()
        s = ""
        lines = []
        for all_stats in stats_list:
            try:
                lines.append(  [f"{all_stats['hostname']}",
                                f"[{format_age(all_stats['age'])}]",
                                f" {all_stats['status']}",
                                f" IP:{all_stats['ip']} ",
                                f" CPU:{all_stats['CPU']} ",
                                f" RAM:{all_stats['RAM']} ",
                                f" GPU:{all_stats['GPU']}",
                                f" VRAM:{all_stats['VRAM']}",
                                f" disk:{all_stats['DISK']}",
                                f" top_mem_user:{all_stats['top_mem_user']}",
                                f" top_vram_users:{all_stats['top_vram_users']}",
                                f" dl:{all_stats['daily_load']*100:.1f}%", 
                                f" wl:{all_stats['weekly_load']*100:.1f}%",
                                f" active_users:{all_stats['active_users']}", 
                                # f" hourly:{ws_status.activity_seconds/ws_status.activity_len*100:.1f}%"
                                ])
            except KeyError as e:
                lines.append(  [f"{all_stats['hostname']}",
                                f"[{format_age(all_stats['age'])}]",
                                f" {all_stats['status']}"])
        
        if len(lines)>0:
            cols = 0
            for line in lines:
                if isinstance(line, list):
                    cols = max(cols, len(line))
            widths = [1]*cols
            for line in lines:
                for i,col in enumerate(line):
                    widths[i] = max(widths[i], len(col)+1)
            for line in lines:
                for i in range(len(line)):
                    line[i] = line[i].ljust(widths[i])
            DISK_COL = 8
            for line, all_stats in zip(lines, stats_list):
                if len(line) <= DISK_COL:
                    continue
                disk_usage_ratio = all_stats.get("disk_usage_ratio", float("nan"))
                if np.isnan(disk_usage_ratio):
                    continue
                if disk_usage_ratio > 0.99:
                    color = "red"
                elif disk_usage_ratio > 0.95:
                    color = "orange"
                else:
                    continue
                cell = line[DISK_COL]
                visible = cell.rstrip()
                trailing = cell[len(visible):]
                line[DISK_COL] = f'<span style="color:{color};">{visible}</span>{trailing}'
            for line in lines:
                l0_length = len(line[0])
                l0_strip = line[0].strip()
                line[0] = f'<a href="/{l0_strip}/recap">{l0_strip}</a>'+" "*(l0_length-len(l0_strip))
                line_str = ("".join(line)+"\n")
                s+= line_str
        
        return s
        
    def _make_link(self, hostname: str):
        return f'<a href="/{hostname}">{hostname}</a>'
    
    def get_stats_recap_table(self):
        stats_list = self.get_stats_recap_dictlist()
        s = ""
        s += "<table>\n"
        for l in stats_list:
            l["hostname"] = self._make_link(l["hostname"])
            l["age"] = format_age(l["age"])
            l["daily_load"] = f"{l['daily_load']*100:.1f}%"
            l["weekly_load"] = f"{l['weekly_load']*100:.1f}%"
        columns = stats_list[0].keys()
        s+= "<tr>" + "".join([f"<th>{col}</th>" for col in columns]) + "</tr>\n"
        import re
        for all_stats in stats_list:
            cells = []
            for col in columns:
                val = all_stats.get(col, '???')
                val_str = str(val)
                # Find all percentages in the cell
                numbers = re.findall(r'(\d+(?:\.\d+)?)%', val_str)
                highlight = any(float(n) >= 90.0 for n in numbers)
                if highlight:
                    val_str = f'<span class="pct-high">{val_str}</span>'
                cells.append(f"<td>{val_str}</td>")
            s += "<tr>\n" + "\n".join(cells) + "</tr>\n"
        s += "</table>\n"
        return s

    def get_stats_recap_dictlist(self):
        t0 = time.monotonic()
        with self.data_rlock:
            lines = []
            for sys, ws_status in self.stats.items():
                age = time.time()-ws_status.last_contact
                try:
                    data = ws_status.data
                    if len(data)<=1:
                        all_stats = {"hostname": sys, "status": f"🟧 ", "age": age, "ip": "N/A"}
                    else:
                        gpus = data["gpu"]
                        top_vram_users_str = ""
                        for gpu in gpus.values():
                            top_vram_user = max(gpu["memratio_by_user"].items(), key=lambda user_ratio: user_ratio[1]) if len(gpu["memratio_by_user"])>0 else ("None",0.0)
                            top_vram_users_str += top_vram_user[0]+f" {top_vram_user[1]*100:.1f}%"
                        cpu_stats = data["cpu"]
                        disk = data.get("disk",None)
                        if disk is not None:
                            disk_usage_ratio = disk['stats']['disk_usage_ratio']
                            disk_str = str([f"{disk_usage_ratio*100:.2f}%" for gpu in gpus.values()])
                        else:
                            disk_usage_ratio = float("nan")
                            disk_str = "N/A"
                        top_mem_user = max(cpu_stats["memratio_by_user"].items(), key=lambda user_ratio: user_ratio[1])
                        top_mem_user_str = top_mem_user[0]+f" {top_mem_user[1]*100:.1f}%"

                        active_users = ws_status.active_users_in_last_minute
                        # active_users_top_proc_age = {u:ws_status.users_top_proc_age.get(u,float("nan")) for u in active_users}
                        active_users_top_proc_age = {u:f"{datetime.timedelta(seconds=int(v))}" if u in active_users else "-" for u,v in ws_status.users_top_proc_age.items()}

                        if age > 120:
                            status = "🟨"
                        elif len(active_users)>0:
                            status = "🟥"
                        else:
                            status = "🟩"
                        hostname = str(data['hostname'])
                        gpus_usage = [f"{gpu['stats']['gpu_proc_utilization_ratio']:.0f}%" for gpu in gpus.values()]
                        if len(gpus_usage) == 1:
                            gpus_usage = gpus_usage[0]
                        elif len(gpus_usage) == 0:
                            gpus_usage = "N/A"
                        vrams_usage = [f"{gpu['stats']['gpu_mem_fill_ratio']*100:.2f}%" for gpu in gpus.values()]
                        if len(vrams_usage) == 1:
                            vrams_usage = vrams_usage[0]
                        elif len(vrams_usage) == 0:
                            vrams_usage = "N/A"
                        all_stats = {"hostname" : hostname,
                                    "age" : age,
                                    "status" : status,
                                    "ip" : data.get('ip', 'N/A'),
                                    "CPU" : f"{cpu_stats['cpu_utilization_ratio']*100:.0f}%",
                                    "RAM" : f"{cpu_stats['cpu_mem_fill_ratio']*100:.2f}%",
                                    "GPU" : str(gpus_usage),
                                    "VRAM" : str(vrams_usage),
                                    "DISK" : disk_str,
                                    "disk_usage_ratio" : disk_usage_ratio,
                                    "top_mem_user" : top_mem_user_str,
                                    "top_vram_users" : top_vram_users_str,
                                    "daily_load" : ws_status.daily_activity_ratio(),
                                    "weekly_load" : ws_status.weekly_activity_ratio(),
                                    "active_users" : [u+"["+str(active_users_top_proc_age.get(u, "-"))+"]" for u in active_users]
                                    }
                        if age > 300:
                            preserved_keys = {"hostname", "status", "age", "ip"}
                            all_stats = {k:(v if k in preserved_keys else (float("nan") if isinstance(v, (int, float, str)) else "???")) for k,v in all_stats.items()}
                    lines.append(all_stats)
                except Exception as e:
                    logger.debug(f"Error interpreting data from {data['hostname']}: {e}")
                    lines.append({"hostname": sys, "status": f"🟧 ", "age": age})
            lines.sort(key=lambda x: str(x['hostname']))
        tf = time.monotonic()
        # print(f"Held lock for {(tf-t0)*1000:.3f}ms")
        return lines

    def get_activity_img(self, ws_name, date : datetime.date | None = None):
        if ws_name in self.stats:
            if date is None:
                date = datetime.datetime.now().date()-datetime.timedelta(days=6) # default to last 7 days
            return self.stats[ws_name].get_usage_stats().get_week_image(date)
        else:
            return None
        
    def get_activity_text(self, ws_name):
        if ws_name in self.stats:
            return self.stats[ws_name].get_usage_stats().get_week_recap()
        else:
            return None
    
    def get_user_activity_images(self, ws_name):
        if ws_name in self.stats:
            return self.stats[ws_name].get_usage_stats().get_week_users_images()
        else:
            return None

    def _merge_user_aliases(self, user_tot_usage: dict[str, int]) -> dict[str, int]:
        if not self._user_alias_lookup:
            return user_tot_usage
        merged: dict[str, int] = {}
        for username, minutes in user_tot_usage.items():
            canonical = self._user_alias_lookup.get(username, username)
            # print(f"Merging user '{username}' into canonical '{canonical}'")
            merged[canonical] = merged.get(canonical, 0) + minutes
        return merged

    def get_total_usage_minutes(self, since_seconds_ago) -> dict[str, int]:
        user_tot_usage: dict[str, int] = {}
        with self.data_rlock:
            for ws_name, ws_status in self.stats.items():
                ws_user_usage = ws_status.usage_minutes_per_user(since_seconds_ago=since_seconds_ago)
                for username, minutes in ws_user_usage.items():
                    if username not in user_tot_usage:
                        user_tot_usage[username] = 0
                    user_tot_usage[username] += minutes
            user_tot_usage = self._merge_user_aliases(user_tot_usage)
        return user_tot_usage
    
    def get_total_usage_ratio(self, since_seconds_ago) -> float:
        ratio_sum = 0.0
        ratio_count = 0
        with self.data_rlock:
            for ws_name, ws_status in self.stats.items():
                active_ratio = ws_status.activity_ratio(since_seconds_ago=since_seconds_ago)
                if not np.isnan(active_ratio):
                    ratio_sum += active_ratio
                    ratio_count += 1
        total_ratio = ratio_sum / ratio_count if ratio_count > 0 else float("nan")
        return total_ratio

    def receiver_worker(self, bind_to : str):
        system_state_topic = b'system_stats'
        ctx = zmq.Context()
        s = ctx.socket(zmq.SUB)
        s.bind(bind_to)
        logger.info(f"Listening on {bind_to}")

        s.setsockopt(zmq.SUBSCRIBE, system_state_topic)
        try:
            while True:
                try:
                    topic, msg = s.recv_multipart()
                    data = json.loads(msg)
                    self.update_stats(data)
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    logger.error(f"receiver_worker: error processing message: {e}")
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
