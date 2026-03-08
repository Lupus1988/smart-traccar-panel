#!/usr/bin/env python3
import json
import math
import time
import gps
import requests

CONFIG = "/opt/van-traccar/config.json"
STATE = "/opt/van-traccar/status.json"
QUEUE = "/opt/van-traccar/queue.json"
QUEUE_MAX = 50

DEFAULT_INTERVAL_STATIONARY = 420
DEFAULT_INTERVAL_MOVING = 5
DEFAULT_MOVEMENT_DISTANCE_M = 30


def load_config():
    with open(CONFIG, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    cfg.setdefault("interval_stationary", DEFAULT_INTERVAL_STATIONARY)
    cfg.setdefault("interval_moving", DEFAULT_INTERVAL_MOVING)
    cfg.setdefault("movement_distance_m", DEFAULT_MOVEMENT_DISTANCE_M)
    return cfg


def write_state(**kwargs):
    state = {
        "last_send_utc": None,
        "last_http_code": None,
        "last_lat": None,
        "last_lon": None,
        "last_accuracy": None,
        "last_error": None,
        "tracking_mode": None,
        "active_interval": None,
        "movement_distance_m": None,
    }
    try:
        with open(STATE, "r", encoding="utf-8") as f:
            state.update(json.load(f))
    except Exception:
        pass

    state.update(kwargs)

    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")
    with open(tmp, "rb") as src, open(STATE, "wb") as dst:
        dst.write(src.read())


def load_queue():
    try:
        with open(QUEUE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def save_queue(queue):
    tmp = QUEUE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(queue[-QUEUE_MAX:], f, indent=2)
        f.write("\n")
    with open(tmp, "rb") as src, open(QUEUE, "wb") as dst:
        dst.write(src.read())


def enqueue_position(payload):
    queue = load_queue()
    queue.append(payload)
    save_queue(queue)


def post_payload(cfg, payload):
    r = requests.post(
        cfg["server_url"],
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10
    )
    print("SEND", r.status_code, payload, flush=True)
    return r


def flush_queue(cfg):
    queue = load_queue()
    if not queue:
        return True

    for i, item in enumerate(queue):
        try:
            r = post_payload(cfg, item)
            if r.status_code < 200 or r.status_code >= 300:
                save_queue(queue[i:])
                write_state(last_http_code=r.status_code, last_error=f"queue_send_failed_http_{r.status_code}")
                return False
        except Exception as e:
            save_queue(queue[i:])
            write_state(last_http_code=None, last_error=f"queue_send_failed: {e}")
            return False

    save_queue([])
    return True


def distance_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1 = math.radians(float(lat1))
    p2 = math.radians(float(lat2))
    dp = math.radians(float(lat2) - float(lat1))
    dl = math.radians(float(lon2) - float(lon1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def send_position(cfg, lat, lon, accuracy, tracking_mode="unbekannt", active_interval=None, movement_distance_m=None, event=None):
    payload = {
        "id": str(cfg["device_id"]),
        "lat": str(lat),
        "lon": str(lon),
        "timestamp": str(int(time.time() * 1000)),
        "accuracy": str(accuracy)
    }
    if event:
        payload["event"] = str(event)

    state_extra = {
        "tracking_mode": tracking_mode,
        "active_interval": active_interval,
        "movement_distance_m": movement_distance_m,
    }

    if not flush_queue(cfg):
        enqueue_position(payload)
        write_state(
            last_http_code=None,
            last_lat=lat,
            last_lon=lon,
            last_accuracy=accuracy,
            last_error="current_position_queued",
            **state_extra,
        )
        return

    try:
        r = post_payload(cfg, payload)

        if 200 <= r.status_code < 300:
            write_state(
                last_send_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                last_http_code=r.status_code,
                last_lat=lat,
                last_lon=lon,
                last_accuracy=accuracy,
                last_error=None,
                **state_extra,
            )
        else:
            enqueue_position(payload)
            write_state(
                last_http_code=r.status_code,
                last_lat=lat,
                last_lon=lon,
                last_accuracy=accuracy,
                last_error=f"http_{r.status_code}_queued",
                **state_extra,
            )

    except Exception as e:
        print("ERROR", e, flush=True)
        enqueue_position(payload)
        write_state(
            last_http_code=None,
            last_lat=lat,
            last_lon=lon,
            last_accuracy=accuracy,
            last_error=f"{e} (queued)",
            **state_extra,
        )


def main():
    cfg = load_config()
    write_state(
        last_send_utc=None,
        last_http_code=None,
        last_lat=None,
        last_lon=None,
        last_accuracy=None,
        last_error=None,
        tracking_mode="init",
        active_interval=int(cfg.get("interval_stationary", DEFAULT_INTERVAL_STATIONARY)),
        movement_distance_m=None,
    )

    save_queue(load_queue())
    session = gps.gps(mode=gps.WATCH_ENABLE)

    last_ref_lat = None
    last_ref_lon = None
    first_position_sent = False

    while True:
        try:
            report = session.next()
        except Exception as e:
            write_state(last_error=f"gps_session_error: {e}")
            time.sleep(2)
            try:
                session = gps.gps(mode=gps.WATCH_ENABLE)
            except Exception:
                time.sleep(3)
            continue

        if report.get("class") != "TPV":
            continue

        lat = getattr(report, "lat", None)
        lon = getattr(report, "lon", None)

        if lat is None or lon is None:
            continue

        accuracy = getattr(report, "epx", 999)

        if not first_position_sent:
            send_position(
                cfg,
                lat,
                lon,
                accuracy,
                tracking_mode="Startposition",
                active_interval=int(cfg.get("interval_stationary", DEFAULT_INTERVAL_STATIONARY)),
                movement_distance_m=None,
                event="boot",
            )
            first_position_sent = True
            last_ref_lat = lat
            last_ref_lon = lon
            time.sleep(int(cfg.get("interval_stationary", DEFAULT_INTERVAL_STATIONARY)))
            continue

        if float(accuracy) > float(cfg["min_accuracy"]):
            time.sleep(1)
            continue

        move_dist = None
        moving = False

        if last_ref_lat is not None and last_ref_lon is not None:
            try:
                move_dist = distance_m(last_ref_lat, last_ref_lon, lat, lon)
                moving = move_dist >= float(cfg.get("movement_distance_m", DEFAULT_MOVEMENT_DISTANCE_M))
            except Exception:
                move_dist = None
                moving = False

        tracking_mode = "Bewegung" if moving else "Stillstand"
        active_interval = int(
            cfg.get("interval_moving", DEFAULT_INTERVAL_MOVING)
            if moving else
            cfg.get("interval_stationary", DEFAULT_INTERVAL_STATIONARY)
        )

        send_position(
            cfg,
            lat,
            lon,
            accuracy,
            tracking_mode=tracking_mode,
            active_interval=active_interval,
            movement_distance_m=(round(move_dist, 1) if move_dist is not None else None),
        )

        if moving:
            last_ref_lat = lat
            last_ref_lon = lon

        time.sleep(active_interval)

def send_current_position_once():
    cfg = load_config()
    session = gps.gps(mode=gps.WATCH_ENABLE)
    deadline = time.time() + 20

    while time.time() < deadline:
        try:
            report = session.next()
        except Exception as e:
            write_state(last_error=f"manual_send_gps_error: {e}")
            time.sleep(1)
            try:
                session = gps.gps(mode=gps.WATCH_ENABLE)
            except Exception:
                pass
            continue

        if report.get("class") != "TPV":
            continue

        lat = getattr(report, "lat", None)
        lon = getattr(report, "lon", None)

        if lat is None or lon is None:
            continue

        accuracy = getattr(report, "epx", 999)

        send_position(
            cfg,
            lat,
            lon,
            accuracy,
            tracking_mode="Manuell",
            active_interval=None,
            movement_distance_m=None,
            event="manual",
        )
        return True

    write_state(last_error="manual_send_timeout_no_tpv")
    return False


if __name__ == "__main__":
    main()
