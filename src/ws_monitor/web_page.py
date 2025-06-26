import flask
from flask import Flask, render_template, redirect, request, url_for, Response
# import flask_login
import cv2
import numpy as np

from ws_monitor.subscriber import Subscriber

# a nice reference can be found at : https://blog.miguelgrinberg.com/post/flask-video-streaming-revisited

# start with: gunicorn --bind 0.0.0.0:9422 adarl.utils.dbg.web_video_streamer_app:app


app = Flask(__name__)
app.secret_key = 'ihavenoideawhatthisis-yetanothertime  bahbehboh'

@app.route('/')
def index():
   newline  = "\n"
   return f'''
<!DOCTYPE html>
<html>
<head>
  <meta http-equiv="refresh" content="1" />
  <title>Workstations Status</title>
</head>  
<body>
 <h1>Workstations Status</h1>
 <pre>
{subscriber.get_stats_recap()}
 </pre> 
</body>
</html>'''



@app.route("/<wsname>/weekimage")
def ws_weekimage_page(wsname):
  img = subscriber.get_activity_img(wsname)
  if img is None:
    return f"{wsname} not found"
  data = np.array(cv2.imencode('.png', img)[1]).tobytes()
  return Response(data,
                  mimetype='image/png')


@app.route("/<wsname>")
def ws_details_page(wsname):
  links = [f'<a href="/{wsname}">{wsname}</a>' for wsname in subscriber.get_ws_names()]
  links = "<br>\n".join(links)

  weekly_recap = subscriber.get_activity_text(wsname)
  if weekly_recap is None:
    weekly_recap = f"{wsname} not found"
  weekly_recap = "\n"+weekly_recap
  return f'''
<html>
  <head>
    <title>{wsname}</title>
    <style>
      img {{
        width: 90%;
      }}
    </style>
  </head>
  <body>
    <h1>{wsname} Weekly activity</h1>
    Weekly activity:
    <br>
    <img src="/{wsname}/weekimage">
    <pre>
    {weekly_recap}
    </pre>
    <br>
    {links}
    <br>
    <br>
    <a href="/">Home</a>
  </body>
</html>'''


with app.app_context():
  subscriber = Subscriber()
   

if __name__ == '__main__':
  app.run(debug=False, host="0.0.0.0")
