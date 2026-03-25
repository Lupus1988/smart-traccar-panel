#!/usr/bin/env bash
set -euo pipefail

POLICY_FILE="/opt/van-panel/vpn-policy.json"
WAIT_SECONDS=25

remember_last_state=0
last_online=0

if [ -f "$POLICY_FILE" ]; then
  readarray -t values < <(/usr/bin/python3 -c 'import json,sys; data=json.load(open(sys.argv[1])); print("1" if data.get("remember_last_state") else "0"); print("1" if data.get("last_online") else "0")' "$POLICY_FILE" 2>/dev/null || printf "0\n0\n")
  remember_last_state="${values[0]:-0}"
  last_online="${values[1]:-0}"
fi

should_start=1
if [ "$remember_last_state" = "1" ] && [ "$last_online" != "1" ]; then
  should_start=0
fi

if [ "$should_start" != "1" ]; then
  exit 0
fi

systemctl start wg-quick@wg0.service >/dev/null 2>&1 || true

for _ in $(seq 1 "$WAIT_SECONDS"); do
  if wg show wg0 latest-handshakes 2>/dev/null | awk '{if ($2 > 0) {found=1}} END{exit(found?0:1)}'; then
    exit 0
  fi
  sleep 1
done

systemctl stop wg-quick@wg0.service >/dev/null 2>&1 || true
