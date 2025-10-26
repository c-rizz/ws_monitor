#!/bin/bash

cd $(dirname $0)
gunicorn -w 4 'ws_monitor.web_page' -b 0.0.0.0:9423
# flask --app ws_monitor.web_page run -p 9423 --host=0.0.0.0
