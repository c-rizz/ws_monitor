import os
import threading
import flask
from flask import Flask, render_template, redirect, request, url_for, Response
# import flask_login
import cv2
import numpy as np
import base64
from datetime import datetime

from ws_monitor.subscriber import Subscriber

# a nice reference can be found at : https://blog.miguelgrinberg.com/post/flask-video-streaming-revisited

# start with: gunicorn --bind 0.0.0.0:9422 adarl.utils.dbg.web_video_streamer_app:app


app = Flask(__name__)
app.secret_key = 'ihavenoideawhatthisis-yetanothertime  bahbehboh'

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


@app.route("/")
def index2():
    # This will render templates/index.html
    return render_template("index.html")

@app.route("/global_stats")
def global_stats():
    # Replace with your subscriber.get_stats_recap(wsname)
    stats = subscriber.get_stats_recap()
    return Response(stats, mimetype="text/plain")

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


@app.route("/<wsname>")
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
  subscriber = Subscriber()

if __name__ == '__main__':
  app.run(debug=False, host="0.0.0.0")
