import os
import threading
import secrets
import math
import flask
from flask import Flask, render_template, redirect, request, url_for, Response, jsonify
# import flask_login
import cv2
import numpy as np
import base64
from datetime import datetime
import pprint
import yaml
from ws_monitor.subscriber import Subscriber

# a nice reference can be found at : https://blog.miguelgrinberg.com/post/flask-video-streaming-revisited

# start with: gunicorn --bind 0.0.0.0:9422 adarl.utils.dbg.web_video_streamer_app:app


BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CONFIG_ENV_VAR = "WSMONITOR_WEB_CONFIG"
DEFAULT_WEB_CONFIG_PATH = os.path.join(BASE_DIR, "config", "web_config.yaml")
SECRET_KEY_ENV_VAR = "WSMONITOR_FLASK_SECRET_KEY"


def load_web_config(config_path: str) -> dict:
  if not os.path.isfile(config_path):
    print(f"web_config: no config file found at {config_path}, using defaults")
    return {}
  try:
    with open(config_path, "r", encoding="utf-8") as config_file:
      return yaml.safe_load(config_file) or {}
  except (OSError, yaml.YAMLError) as exc:
    print(f"web_config: failed to load {config_path}: {exc}")
    return {}


def build_user_alias_lookup(alias_section) -> dict[str, str]:
  lookup: dict[str, str] = {}
  if not isinstance(alias_section, dict):
    return lookup
  for canonical, aliases in alias_section.items():
    if not isinstance(canonical, str):
      continue
    if aliases is None:
      normalized_aliases: list[str] = []
    elif isinstance(aliases, str):
      normalized_aliases = [aliases]
    elif isinstance(aliases, (list, tuple, set)):
      normalized_aliases = [alias for alias in aliases if isinstance(alias, str)]
    else:
      continue
    for alias in normalized_aliases:
      lookup[alias] = canonical
    lookup.setdefault(canonical, canonical)
  return lookup


def get_flask_secret_key() -> str:
  secret = os.environ.get(SECRET_KEY_ENV_VAR)
  if secret:
    return secret
  secret = secrets.token_hex(32)
  print(f"flask_secret: generated ephemeral key because {SECRET_KEY_ENV_VAR} is unset")
  return secret


WEB_CONFIG_PATH = os.environ.get(CONFIG_ENV_VAR, DEFAULT_WEB_CONFIG_PATH)
WEB_CONFIG = load_web_config(WEB_CONFIG_PATH)
USER_ALIAS_LOOKUP = build_user_alias_lookup(WEB_CONFIG.get("user_aliases", {}))
SERVER_BOOT_ID = secrets.token_hex(8)

app = Flask(__name__)
app.secret_key = get_flask_secret_key()
_resource_requests : list[dict] = []

@app.route('/index_old')
def index():
   newline  = "\n"
   css_url = url_for('static', filename='no_style.css')
   return f'''
<!DOCTYPE html>
<html>
<head>
  <meta http-equiv="refresh" content="1" />
  <link rel="stylesheet" href="{css_url}">
  <title>Workstations Status</title>
</head>  
<body>
 <h1>Workstations Status</h1>
{subscriber.get_stats_recap_table()}
</body>
</html>'''

@app.errorhandler(404)
def page_not_found(e):
    return "Page not found", 404

@app.route("/")
def index2():
    # This will render templates/index.html
    notice = WEB_CONFIG.get("notice_html", "")
    return render_template("index.html", notice=notice)

@app.route("/global_stats")
def global_stats():
    # Replace with your subscriber.get_stats_recap(wsname)
    stats = subscriber.get_stats_recap()
    return Response(stats, mimetype="text/plain")

@app.route("/user_usage_percent_<int:duration_sec>")
def user_usage_percent(duration_sec):
  duration = duration_sec  # duration in seconds
  usage_minutes = subscriber.get_total_usage_minutes(since_seconds_ago=duration)
  total_minutes = duration // 60
  usage_percent = {user: (minutes / total_minutes) * 100 for user, minutes in usage_minutes.items() if total_minutes > 0}
  usage_percent = {k: v for k, v in usage_percent.items() if v >= 0.1}
  sorted_usage = sorted(usage_percent.items(), key=lambda item: item[1], reverse=True)

  if not sorted_usage:
    usage_percent_text = ""
  else:
    max_name_len = max(len(user) for user, _ in sorted_usage)
    rows = []
    for user, percent in sorted_usage:

      
      if percent > 300:
          color = "🟪" #"🫠"
      elif percent > 200:
          color = "🟥" #"😡"
      elif percent > 100:
          color = "🟨" #"😐"
      elif percent > 50:
          color = "🟩" #"🙂"
      else:
          color = "⬜" #"🙃"
      rows.append(f"{color} {user.ljust(max_name_len)}  {percent:6.2f}%")
    usage_percent_text = "\n".join(rows)
  return Response(usage_percent_text, mimetype="text/plain")


@app.route("/total_usage_ratio_<int:duration_sec>")
def total_usage_ratio(duration_sec):
  ratio = subscriber.get_total_usage_ratio(since_seconds_ago=duration_sec)
  if math.isnan(ratio):
    ratio_payload = None
  else:
    ratio_payload = ratio
  return jsonify({"ratio": ratio_payload, "duration_sec": duration_sec})


@app.route("/request_resources", methods=["POST"])
def request_resources():
  payload = request.get_json(silent=True) or {}
  user = (payload.get("user") or "anonymous").strip() or "anonymous"
  now = datetime.now()
  timestamp = datetime.strftime(now, "%H:%M:%S")
  entry = {"user": user, "timestamp": timestamp, "datetime": now}
  _resource_requests.append(entry)
  if len(_resource_requests) > 10:
    del _resource_requests[:-10]
  print(f"Resource request received from {user} at {timestamp}")
  return jsonify({"status": "ok"})

@app.route("/request_resources", methods=["GET"])
def list_resource_requests():
  reqs_no_old = []
  now = datetime.now()
  for r in _resource_requests:
    delta = now - r["datetime"]
    if delta.total_seconds() <= 3600:
      reqs_no_old.append(r)
  _resource_requests.clear()
  _resource_requests.extend(reqs_no_old)
  reqs = [{"user": r["user"], "timestamp": r["timestamp"]} for r in reversed(_resource_requests)]
  return jsonify(list(reversed(reqs)))


@app.route("/server_boot_id")
def server_boot_id():
  return jsonify({"boot_id": SERVER_BOOT_ID})

@app.route("/<wsname>/weekimage_history_<date_yyyymmdd>")
def ws_weekimage_history_page(wsname, date_yyyymmdd):
  img = subscriber.get_activity_img(wsname, date = datetime.strptime(date_yyyymmdd, "%Y%m%d").date())
  if img is None:
    return f"{wsname} not found"
  data = np.array(cv2.imencode('.png', img)[1]).tobytes()
  return Response(data,
                  mimetype='image/png')

@app.route("/<wsname>/weekimage")
def ws_weekimage_page(wsname):
  img = subscriber.get_activity_img(wsname)
  if img is None:
    return f"{wsname} not found"
  data = np.array(cv2.imencode('.png', img)[1]).tobytes()
  return Response(data,
                  mimetype='image/png')

def get_page_foot():
  links = [f'<a href="/{wsname}">{wsname}</a>' for wsname in subscriber.get_ws_names()]
  return f"""
<br>
{'<br> '.join(links)}
<br>
<br>
<a href="/">Home</a>"""

@app.route("/<wsname>/users")
def ws_weekuserimage_page(wsname):
  imgs : dict[str,np.ndarray] | None = subscriber.get_user_activity_images(wsname)
  if imgs is None:
    return f"{wsname} not found"
  
  user_images = {}
  for username, img in imgs.items():
      success, encoded = cv2.imencode('.png', img)
      if success:
          b64_data = base64.b64encode(encoded.tobytes()).decode('utf-8')
          user_images[username] = b64_data
      else:
          user_images[username] = None

  return render_template("ws_users.html",
                        wsname=wsname,
                        user_images=user_images,
                        ws_names=subscriber.get_ws_names())


@app.route("/<wsname>/recap")
def ws_details_page(wsname):
  weekly_recap = subscriber.get_activity_text(wsname)
  if weekly_recap is None:
    weekly_recap = f"{wsname} not found"
  weekly_recap = "\n"+weekly_recap
  return render_template("ws_details.html", 
                        wsname=wsname, 
                        weekly_recap=weekly_recap,
                        ws_names=subscriber.get_ws_names())


with app.app_context():
  subscriber = Subscriber(user_alias_lookup=USER_ALIAS_LOOKUP)

if __name__ == '__main__':
  app.run(debug=False, host="0.0.0.0")
