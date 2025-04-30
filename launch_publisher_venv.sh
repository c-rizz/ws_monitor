#!/bin/bash

venv_folder=$1
config_file=$2
if [ -z "$config_file" ]; then
    echo "Usage: $0 <venv_folder> <config_file>"
    exit 1
fi
if [ -z "$venv_folder" ]; then
    echo "Usage: $0 <venv_folder> <config_file>"
    exit 1
fi

if [ ! -f "$config_file" ]; then
    echo "Config file $config_file does not exist."
    exit 1
fi
if [ ! -d "$venv_folder" ]; then
    echo "Virtual environment folder $venv_folder does not exist."
    exit 1
fi


source "$venv_folder/bin/activate"
if [ $? -ne 0 ]; then
    echo "Failed to activate virtual environment."
    exit 1
fi
echo "Virtual environment activated. Launching publisher..."

python3 -u -m ws_monitor.publisher --config $config_file
if [ $? -ne 0 ]; then
    echo "Failed to launch publisher."
    exit 1
fi