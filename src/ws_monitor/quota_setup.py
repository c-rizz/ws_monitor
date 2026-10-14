import os
import sys


def main() -> None:
    """Runs the bundled setup_quota_monitoring.sh as root. It goes through sudo itself rather than
    expecting `sudo wsmon-setup-quota`, since pipx's ~/.local/bin isn't on root's PATH under sudo."""
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "setup_quota_monitoring.sh")
    cmd = ["bash", script, *sys.argv[1:]]
    if os.geteuid() != 0:
        cmd = ["sudo", *cmd]
    os.execvp(cmd[0], cmd)
