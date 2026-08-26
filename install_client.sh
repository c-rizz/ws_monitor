#!/bin/bash

# Get folder where the install script is located
cd $(dirname $0)
dname=$(realpath $(dirname $0))

if ! python3 -m pipx --version >/dev/null 2>&1; then
    echo "pipx not found, installing it for the current user (no sudo needed)..."
    python3 -m pip install --user pipx || python3 -m pip install --user pipx --break-system-packages
fi
python3 -m pipx ensurepath >/dev/null
export PATH="$HOME/.local/bin:$PATH"

echo "Installing ws_monitor with pipx..."
python3 -m pipx install --force "$dname"

if ! command -v wsmon-publisher >/dev/null 2>&1; then
    echo "wsmon-publisher not found on PATH after installing."
    echo "Open a new shell (so it picks up ~/.local/bin) and re-run this script."
    exit 1
fi

echo ""
echo "What is the server address? (default: 'localhost:9452')"
read -p "> " -r server_address
if [[ -z "$server_address" ]]; then
    server_address="localhost:9452"
fi

config_dir="$HOME/.config/ws_monitor"
mkdir -p "$config_dir"
sed -e "s#localhost:9452#$server_address#g" default_pub_config.yaml > "$config_dir/publisher_config.yaml"
if [[ ! -f "$config_dir/publisher_config.yaml" ]]; then
    echo "Error: Failed to create $config_dir/publisher_config.yaml"
    exit 1
fi
echo "Wrote $config_dir/publisher_config.yaml"

echo "Do you want to start the publisher at startup? (y/N)"
read -p "> " -r start_at_boot
if [[ "$start_at_boot" == "y" || "$start_at_boot" == "Y" ]]; then
    wsmon-publisher --config "$config_dir/publisher_config.yaml" --install-service
else
    echo "Not starting publisher at boot. Run it manually with: wsmon-publisher --config $config_dir/publisher_config.yaml"
fi
