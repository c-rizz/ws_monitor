# WORKSTATION MONITOR

WSMONITOR is a very simple and lightweight tool for monitoring a group of independently managed computers.

You have a bunch of linux workstations in your lab and you want to keep track of which ones are free and who is using which?
You don't want to install complex tools and have something that is minimal and easy to install?
This may be the package for you.

This package will run:

* A worker on each workstation monitoring its CPU/GPU/RAM/VRAM/Disk resources
* On a single computer, a simple webserver displaying a recap of the status of each workstation.

On the main webpage you will get a recap like the following:

![WSMonitor screenshot](example_images/wsmonitor.png)

For each workstation then you can see the weekly usage history, also user by user.

## Installation

### On the server:

```
git clone https://github.com/c-rizz/ws_monitor
cd ws_monitor
pyhton3 -m venv virtualenv
. virtualenv/bin/activate
pip install .
```

The webserver is not yet set up to be  started on boot, so you will need to start it manually:

```
cd ws_monitor
. virtualenv/bin/activate
wsmon_run_flask.sh
```


### On the workstations:

```
git clone https://github.com/c-rizz/ws_monitor
cd ws_monitor
./install.sh # this requires sudo rights, but you may be able to also run things manually without it, just check the contents
```

