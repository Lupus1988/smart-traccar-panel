#!/usr/bin/env bash
set -u

LOG="/var/log/van-wifi-autofallback.log"
WIFI_IF="wlan0"
HOTSPOT_CONN="van-hotspot"

ts() { date '+%F %T'; }

{
  echo "[$(ts)] --- run ---"
  echo "[$(ts)] nmcli device:"
  nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device status || true
  echo "[$(ts)] nmcli active:"
  nmcli -t -f NAME,TYPE,DEVICE connection show --active || true

  current_conn="$(nmcli -t -f DEVICE,CONNECTION device status | awk -F: -v d="$WIFI_IF" '$1==d {print $2; exit}')"
  wifi_state="$(nmcli -t -f DEVICE,TYPE,STATE device status | awk -F: -v d="$WIFI_IF" '$1==d && $2=="wifi" {print $3; exit}')"

  echo "[$(ts)] current_conn=$current_conn"
  echo "[$(ts)] wifi_state=$wifi_state"

  if [ "$current_conn" = "$HOTSPOT_CONN" ]; then
    echo "[$(ts)] hotspot already active -> exit"
    exit 0
  fi

  if [ "$wifi_state" = "connected" ] && [ "$current_conn" != "--" ] && [ -n "$current_conn" ]; then
    echo "[$(ts)] wifi connected -> ensure hotspot down"
    nmcli connection down "$HOTSPOT_CONN" >/dev/null 2>&1 || true
    exit 0
  fi

  echo "[$(ts)] wifi not connected -> try hotspot up"
  nmcli connection up "$HOTSPOT_CONN" || true

  echo "[$(ts)] after hotspot up:"
  nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device status || true
  nmcli -t -f NAME,TYPE,DEVICE connection show --active || true
} >> "$LOG" 2>&1
