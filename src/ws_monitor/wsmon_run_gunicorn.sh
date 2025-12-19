#!/bin/bash

cd $(dirname $0)

# Keep a single worker: the Subscriber binds the ZMQ port, and multiple
# gunicorn workers would all try to bind the same endpoint causing EADDRINUSE.
# Threads are fine—they share the single subscriber instance.
gunicorn -w 1 --threads 4 'ws_monitor.web_page:app' -b 0.0.0.0:9423
# flask --app ws_monitor.web_page run -p 9423 --host=0.0.0.0
