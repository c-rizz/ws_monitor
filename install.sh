#!/bin/bash

# Get folder where the install script is located
cd $(dirname $0)
dname=$(realpath $(dirname $0))
sudo apt update && sudo apt install -y smem python3-venv
rm -rf virtualenv
python3 -m venv virtualenv
. virtualenv/bin/activate
if [[ "$(which python3)" != "$dname/virtualenv/bin/python3" ]]; then
    echo "Failed to enter venv."
    exit 1
fi

echo "Created venv at $(which python3)" 
pip install --upgrade pip
pip install --upgrade setuptools
pip install --upgrade wheel
# pip install -r "${dname}/requirements.txt"
pip install .

echo ""
echo "What is the server address? (default: 'localhost:9452')"
read -p "> " -r server_address
if [[ -z "$server_address" ]]; then
    server_address="localhost:9452"
fi

mkdir -p config
sed -e "s#localhost:9452#$server_address#g" default_pub_config.yaml > config/publisher_config.yaml
if [[ ! -f config/publisher_config.yaml ]]; then
    echo "Error: Failed to create config/publisher_config.yaml"
    exit 1
fi
sed -e "s#PACKAGE_FOLDER#$dname#g" wsmonitor_publisher.service.base > config/wsmonitor_publisher.service
if [[ ! -f config/wsmonitor_publisher.service ]]; then
    echo "Error: Failed to create config/wsmonitor_publisher.service"
    exit 1
fi

echo "Do you want to start the publisher at startup? (y/N)"
read -p "> " -r start_at_boot
if [[ "$start_at_boot" == "y" || "$start_at_boot" == "Y" ]]; then
    sudo cp config/wsmonitor_publisher.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable wsmonitor_publisher.service
    sudo systemctl start wsmonitor_publisher.service
    echo "Service enabled and started. Should be already running."
else
    echo "Not starting publisher at boot."
fi
