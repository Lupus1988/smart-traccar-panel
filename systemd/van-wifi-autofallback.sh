#!/usr/bin/env bash
set -euo pipefail

WIFI_IF="wlan0"
HOTSPOT_CONN="van-hotspot"

current_conn="$(nmcli -t -f DEVICE,CONNECTION device status | awk -F: -v d="$WIFI_IF" '$1==d {print $2; exit}')"
wifi_state="$(nmcli -t -f DEVICE,TYPE,STATE device status | awk -F: -v d="$WIFI_IF" '$1==d && $2=="wifi" {print $3; exit}')"

if [ "$current_conn" = "$HOTSPOT_CONN" ]; then
  exit 0
fi

if [ "$wifi_state" = "connected" ] && [ "$current_conn" != "--" ] && [ -n "$current_conn" ]; then
  nmcli connection down "$HOTSPOT_CONN" >/dev/null 2>&1 || true
  exit 0
fi

nmcli connection up "$HOTSPOT_CONN" >/dev/null 2>&1 || true
