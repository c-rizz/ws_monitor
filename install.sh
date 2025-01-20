#!/bin/bash

# Get folder where the install script is located
cd $(dirname $0)
dname=$(realpath $(dirname $0))
sudo apt install -y smem python3-venv
rm -rf virtualenv
mkdir virtualenv
cd virtualenv
python3 -m venv wsmonitorvenv
. wsmonitorvenv/bin/activate
if [[ "$(which python3)" != "$dname/virtualenv/wsmonitorvenv/bin/python3" ]]; then
    echo "Failed to enter venv."
    exit 1
fi

echo "Created venv at $(which python3)" 
pip install --upgrade pip
pip install --upgrade setuptools
pip install --upgrade wheel

pip install -r "${dname}/requirements.txt"