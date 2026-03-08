#!/usr/bin/env python3
import json
import time
import requests

CONFIG = "/opt/van-traccar/config.json"

cfg = json.load(open(CONFIG, "r", encoding="utf-8"))

payload = {
    "id": str(cfg["device_id"]),
    "lat": "50",
    "lon": "7",
    "timestamp": str(int(time.time() * 1000)),
    "accuracy": "10",
}

r = requests.post(
    cfg["server_url"],
    data=payload,
    headers={"Content-Type": "application/x-www-form-urlencoded"},
    timeout=10,
)

print(r.status_code)
