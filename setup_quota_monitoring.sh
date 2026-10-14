#!/bin/bash
# Enables per-user disk usage accounting (quotas with no limits set) on one filesystem,
# and installs a root cron job that periodically dumps `repquota` output to a
# world-readable file, so the unprivileged ws_monitor publisher can read per-user
# disk usage without ever needing sudo itself.
#
# Usage: sudo ./setup_quota_monitoring.sh [mountpoint] [interval_minutes]
#   mountpoint        filesystem to account (default: /)
#   interval_minutes  how often to refresh the dump, 1-59 (default: 15)
#
# Safe to re-run: steps that are already done are skipped.

set -euo pipefail

MOUNTPOINT="${1:-/}"
INTERVAL_MIN="${2:-15}"
FSTAB=/etc/fstab
DUMP_DIR=/var/lib/ws_monitor
DUMP_FILE="$DUMP_DIR/quota_dump.txt"
CRON_FILE=/etc/cron.d/ws_monitor_quota

die() { echo "Error: $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "must be run as root (sudo $0 $*)"
[[ "$INTERVAL_MIN" =~ ^[0-9]+$ ]] && (( INTERVAL_MIN >= 1 && INTERVAL_MIN <= 59 )) \
    || die "interval_minutes must be an integer between 1 and 59"

if ! command -v quotacheck >/dev/null || ! command -v quotaon >/dev/null || ! command -v repquota >/dev/null; then
    command -v apt-get >/dev/null || die "quota tools not found; install your distribution's 'quota' package and re-run"
    echo "Installing the 'quota' package..."
    apt-get install -y quota
fi
QUOTACHECK=$(command -v quotacheck)
QUOTAON=$(command -v quotaon)
REPQUOTA=$(command -v repquota)

FSTYPE=$(findmnt -n -o FSTYPE --mountpoint "$MOUNTPOINT") || die "$MOUNTPOINT is not a mount point"
case "$FSTYPE" in
    ext2|ext3|ext4) ;;
    *) die "$MOUNTPOINT is $FSTYPE; this script only handles ext2/3/4 (e.g. xfs quotas can't be enabled without unmounting)" ;;
esac

SOURCE=$(findmnt -n -o SOURCE --mountpoint "$MOUNTPOINT")
quota_state=$("$QUOTAON" -pu "$MOUNTPOINT" 2>&1 || true)
if tune2fs -l "$SOURCE" 2>/dev/null | grep '^Filesystem features:' | grep -qw quota; then
    # ext4's native quota feature tracks usage in hidden inodes, always on, nothing to enable.
    # (It can only be turned on with the filesystem unmounted, which is why we don't do it here.)
    echo "$MOUNTPOINT uses ext4's native quota feature, skipping enable steps."
elif [[ "$quota_state" == *"is on"* ]]; then
    echo "User quota accounting is already on for $MOUNTPOINT, skipping enable steps."
else
    matches=$(awk -v mp="$MOUNTPOINT" '$1 !~ /^#/ && NF >= 4 && $2 == mp' "$FSTAB" | wc -l)
    [[ "$matches" -eq 1 ]] || die "expected exactly one active $FSTAB entry for $MOUNTPOINT, found $matches"

    tmp=$(mktemp)
    awk -v mp="$MOUNTPOINT" '
        $1 !~ /^#/ && NF >= 4 && $2 == mp && ("," $4 ",") !~ /,usrquota,/ { $4 = $4 ",usrquota" }
        { print }
    ' "$FSTAB" > "$tmp"

    backup=""
    if ! cmp -s "$FSTAB" "$tmp"; then
        backup="$FSTAB.bak-ws_monitor-$(date +%Y%m%d%H%M%S)"
        cp -p "$FSTAB" "$backup"
        cat "$tmp" > "$FSTAB"  # cat rather than mv, to keep fstab's own inode, owner and mode
        echo "Added usrquota to the $MOUNTPOINT entry in $FSTAB (backup: $backup)"
    fi
    rm -f "$tmp"

    # Only changes mount flags in place: no unmount, no interruption to running processes.
    # Re-reads fstab, so a broken entry fails here instead of at the next boot.
    if ! mount -o remount "$MOUNTPOINT"; then
        if [[ -n "$backup" ]]; then
            cat "$backup" > "$FSTAB"
            echo "Remount failed; restored $FSTAB from $backup" >&2
        fi
        die "remount of $MOUNTPOINT failed"
    fi

    echo "Building initial per-user usage counts (scans the whole filesystem, may take a while)..."
    # -m: count on the live, read-write filesystem instead of trying to remount it read-only first
    "$QUOTACHECK" -cum "$MOUNTPOINT"
    "$QUOTAON" -uv "$MOUNTPOINT"
fi

mkdir -p "$DUMP_DIR"
chmod 755 "$DUMP_DIR"
printf -v q_mp '%q' "$MOUNTPOINT"
# -p prints grace times as plain numbers, keeping the columns stable for parsing.
# Written to a temp file and renamed, so readers never see a half-written dump.
dump_cmd="umask 022; $REPQUOTA -u -p $q_mp > $DUMP_FILE.tmp && mv $DUMP_FILE.tmp $DUMP_FILE"

cat > "$CRON_FILE" <<EOF
# Installed by ws_monitor's setup_quota_monitoring.sh: refreshes per-user disk usage for the publisher.
SHELL=/bin/sh
*/$INTERVAL_MIN * * * * root $dump_cmd
EOF
chmod 644 "$CRON_FILE"
echo "Installed $CRON_FILE (every $INTERVAL_MIN min)"

sh -c "$dump_cmd"
echo "Initial dump written to $DUMP_FILE:"
cat "$DUMP_FILE"
