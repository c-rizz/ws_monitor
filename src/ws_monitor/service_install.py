import getpass
import os
import subprocess


def install_user_service(service_name: str, description: str, exec_start: str, restart_sec: int = 10) -> None:
    """Write, enable and start a systemd --user service, and enable lingering
    so it also runs at boot without needing an active login session.

    Uses `systemctl --user` instead of a system-wide unit so no sudo is
    needed anywhere in this flow (matches how the publisher already reads
    other users' /proc entries without elevated privileges).
    """
    unit_dir = os.path.join(os.path.expanduser("~"), ".config", "systemd", "user")
    os.makedirs(unit_dir, exist_ok=True)
    unit_path = os.path.join(unit_dir, f"{service_name}.service")
    unit_content = (
        f"[Unit]\n"
        f"Description={description}\n"
        f"After=network.target\n"
        f"\n"
        f"[Service]\n"
        f"Type=simple\n"
        f"ExecStart={exec_start}\n"
        f"Restart=on-failure\n"
        f"RestartSec={restart_sec}\n"
        f"\n"
        f"[Install]\n"
        f"WantedBy=default.target\n"
    )
    with open(unit_path, "w", encoding="utf-8") as f:
        f.write(unit_content)
    print(f"Wrote systemd user unit to {unit_path}")

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", service_name], check=True)
    print(f"Enabled and started '{service_name}' (check with: systemctl --user status {service_name})")

    user = getpass.getuser()
    linger = subprocess.run(["loginctl", "show-user", user, "-p", "Linger"],
                             capture_output=True, text=True)
    if "Linger=yes" not in linger.stdout:
        try:
            subprocess.run(["loginctl", "enable-linger", user], check=True)
            print(f"Enabled lingering for '{user}' so the service also starts at boot without a login session.")
        except (subprocess.CalledProcessError, FileNotFoundError):
            print(f"Warning: could not enable lingering automatically. Run 'loginctl enable-linger {user}' "
                  f"yourself (no sudo needed) so the service starts at boot even before you log in.")
