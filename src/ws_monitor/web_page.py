import flask
from flask import Flask, render_template, redirect, request, url_for, Response
# import flask_login

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

with app.app_context():
  subscriber = Subscriber()
   

if __name__ == '__main__':
  app.run(debug=False, host="0.0.0.0")
