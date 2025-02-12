#!/bin/bash

cd $(dirname $0)
flask --app ws_monitor.web_page run -p 9423 --host=0.0.0.0
