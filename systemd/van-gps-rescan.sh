#!/usr/bin/env bash
set -euo pipefail

has_serial=0
for pattern in /dev/serial/by-id/* /dev/ttyUSB* /dev/ttyACM* /dev/serial0; do
  for dev in $pattern; do
    if [ -e "$dev" ]; then
      has_serial=1
      break 2
    fi
  done
done

if [ "$has_serial" != "1" ]; then
  exit 0
fi

if timeout 4 gpspipe -w -n 4 2>/dev/null | grep -qE '"class":"(TPV|DEVICE|DEVICES|SKY)"'; then
  exit 0
fi

udevadm trigger --subsystem-match=tty >/dev/null 2>&1 || true
systemctl restart gpsd.socket >/dev/null 2>&1 || true
systemctl restart gpsd.service >/dev/null 2>&1 || true
