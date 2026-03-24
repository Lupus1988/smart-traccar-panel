import html
import json
import os
import secrets
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, unquote

from flask import Flask, request, redirect, session, url_for
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

CONFIG_TRACCAR = "/opt/van-traccar/config.json"
STATE_TRACCAR = "/opt/van-traccar/status.json"
QUEUE_TRACCAR = "/opt/van-traccar/queue.json"
WG_CONF = "/etc/wireguard/wg0.conf"
AUTH_FILE = Path("/opt/van-panel/auth.json")
SECRET_FILE = Path("/opt/van-panel/secret.key")
AUDIT_LOG_FILE = Path("/opt/van-panel/audit.log")

SESSION_TIMEOUT_MINUTES = 20
RESET_PIN_MAX_ATTEMPTS = 5
RESET_PIN_LOCK_SECONDS = 900
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCK_SECONDS = 600

CSS = """
<style>
:root { color-scheme: dark; }
body{
  margin:0; font-family: system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, Arial, sans-serif;
  background:#0b0f14; color:#e6edf3;
}
a{ color:#7dd3fc; text-decoration:none; }
a:hover{ text-decoration:underline; }
.container{ max-width:980px; margin:0 auto; padding:24px; }
.card{
  background:#0f1720; border:1px solid #1f2a37; border-radius:16px;
  box-shadow: 0 10px 30px rgba(0,0,0,.35);
  padding:18px 18px;
}
.header{ display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:14px; }
.h1{ font-size:20px; font-weight:700; letter-spacing:.2px; margin:0; }
.badge{
  font-size:12px; padding:6px 10px; border-radius:999px;
  border:1px solid #233244; background:#0b1220; color:#a5b4fc;
}
.small{ color:#9aa4b2; font-size:13px; line-height:1.4; margin:8px 0 0; }
.table{ width:100%; border-collapse:separate; border-spacing:0 10px; }
.row{ background:#0b1220; border:1px solid #1f2a37; border-radius:14px; }
td{ padding:12px 12px; vertical-align:middle; }
.ssid{ font-weight:650; }
.mono{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace; }
.pill{
  display:inline-block; font-size:12px; padding:4px 8px; border-radius:999px;
  background:#111827; border:1px solid #263244; color:#9aa4b2;
}
.sig{ width:120px; }
.bar{ height:10px; border-radius:999px; background:#111827; border:1px solid #263244; overflow:hidden; }
.fill{ height:100%; background:linear-gradient(90deg,#22c55e,#84cc16,#eab308,#f97316,#ef4444); }
.btn{
  display:inline-block; padding:9px 12px; border-radius:12px;
  border:1px solid #243244; background:#0f1a2a; color:#e6edf3; cursor:pointer;
}
.btn:hover{ background:#13223a; }
select{
  width:100%; max-width:520px;
  padding:10px 12px; border-radius:12px;
  border:1px solid #263244; background:#0b1220; color:#e6edf3;
  outline:none;
}
select:focus{
  border-color:#60a5fa; box-shadow:0 0 0 4px rgba(96,165,250,.15);
}
input[type=password], input[type=text], input[type=number]{
  width:100%; max-width:520px;
  padding:10px 12px; border-radius:12px;
  border:1px solid #263244; background:#0b1220; color:#e6edf3;
  outline:none;
}
input[type=password]:focus, input[type=text]:focus, input[type=number]:focus{
  border-color:#60a5fa; box-shadow:0 0 0 4px rgba(96,165,250,.15);
}
label{ display:block; font-size:13px; color:#cbd5e1; margin-top:14px; margin-bottom:6px; }
.hr{ border:0; border-top:1px solid #1f2a37; margin:14px 0; }
.notice{
  margin-top:12px; padding:10px 12px; border-radius:12px;
  border:1px solid #243244; background:#0b1220; color:#9aa4b2;
}
.ok{ border-color:#14532d; background:#071a10; color:#86efac; }
.err{ border-color:#7f1d1d; background:#1a0a0a; color:#fecaca; }
.nav{
  display:flex; gap:10px; align-items:center; margin-bottom:14px;
}
.nav a{
  padding:8px 12px; border-radius:12px; border:1px solid #243244;
  background:#0b1220; color:#e6edf3;
}
.nav a.active{ border-color:#60a5fa; box-shadow:0 0 0 4px rgba(96,165,250,.12); }
.grid{
  display:grid;
  gap:12px;
  grid-template-columns: repeat(12, 1fr);
}

.kpi{
  grid-column: span 6;
}

/* Tablet */
@media (max-width: 900px){
  .kpi{
    grid-column: span 6;
  }
}

/* Smartphone */
@media (max-width: 600px){
  .kpi{
    grid-column: span 12;
  }

  .container{
    padding:14px;
  }

  .card{
    padding:14px;
  }

  .h1{
    font-size:18px;
  }

  .btn{
    width:100%;
    text-align:center;
  }

  input[type=text],
  input[type=password],
  input[type=number]{
    max-width:100%;
  }

  .nav{
    flex-wrap:wrap;
  }
}
.kpi .title{ font-size:12px; color:#9aa4b2; margin:0; }
.kpi .value{ font-size:16px; font-weight:700; margin:6px 0 0; }
</style>
"""


def load_json(path, default):
    try:
        if not path.exists():
            return default
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(path)


def load_or_create_secret_key():
    if SECRET_FILE.exists():
        try:
            return SECRET_FILE.read_text(encoding="utf-8").strip()
        except Exception:
            pass

    SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    secret_key = secrets.token_hex(32)
    SECRET_FILE.write_text(secret_key, encoding="utf-8")
    try:
        SECRET_FILE.chmod(0o600)
    except Exception:
        pass
    return secret_key


def load_auth():
    data = load_json(AUTH_FILE, {})
    return data if isinstance(data, dict) else {}


def save_auth(data):
    save_json(AUTH_FILE, data)
    try:
        AUTH_FILE.chmod(0o600)
    except Exception:
        pass


def is_auth_configured():
    data = load_auth()
    return bool(data.get("username") and data.get("password_hash") and data.get("reset_pin_hash"))


def write_audit_log(message):
    AUDIT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with AUDIT_LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"{timestamp} {message}\n")
    try:
        AUDIT_LOG_FILE.chmod(0o600)
    except Exception:
        pass


def init_auth_defaults():
    data = load_auth()
    changed = False
    defaults = {
        "username": "",
        "password_hash": "",
        "reset_pin_hash": "",
        "failed_reset_attempts": 0,
        "reset_locked_until": 0,
        "failed_login_attempts": 0,
        "login_locked_until": 0,
        "created_at": "",
        "updated_at": "",
    }
    for key, value in defaults.items():
        if key not in data:
            data[key] = value
            changed = True
    if changed:
        save_auth(data)


def is_session_valid():
    if not session.get("logged_in"):
        return False

    last_seen = session.get("last_seen", 0)
    now = int(time.time())

    if not isinstance(last_seen, int):
        try:
            last_seen = int(last_seen)
        except Exception:
            last_seen = 0

    if now - last_seen > SESSION_TIMEOUT_MINUTES * 60:
        session.clear()
        return False

    session["last_seen"] = now
    session.permanent = False
    return True


@app.before_request
def enforce_auth():
    open_paths = {"/login", "/setup", "/reset-access", "/factory-reset"}
    path_req = request.path or "/"

    if path_req.startswith("/static"):
        return

    if not is_auth_configured():
        if path_req != "/setup":
            return redirect(url_for("setup"), code=303)
        return

    if path_req in open_paths:
        return

    if not is_session_valid():
        return redirect(url_for("login"), code=303)


@app.after_request
def apply_security_headers(response):
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self' 'unsafe-inline' data: blob:; "
        "img-src 'self' data: blob:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; "
        "form-action 'self'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'"
    )
    return response

def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)

def html_page(body, title="Traccar Client Panel", refresh_seconds=None):
    refresh = f"<meta http-equiv='refresh' content='{int(refresh_seconds)}'>" if refresh_seconds else ""

    footer = """
    <div style='margin-top:40px;text-align:center;font-size:12px;color:#6b7280'>
        Smart Traccar Panel v1.0 · by Lupus1988
    </div>
    """

    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"{refresh}{CSS}<title>{html.escape(title)}</title></head>"
        f"<body><div class='container'>{body}{footer}</div></body></html>"
    )


def public_page(body, title="Traccar Client Panel"):
    footer = """
    <div style='margin-top:40px;text-align:center;font-size:12px;color:#6b7280'>
        Smart Traccar Panel v1.0 · by Lupus1988
    </div>
    """
    wrapped = "<div class='card' style='max-width:640px;margin:40px auto 0 auto'>" + body + "</div>"
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"{CSS}<title>{html.escape(title)}</title></head>"
        f"<body><div class='container'>{wrapped}{footer}</div></body></html>"
    )

def nav(active):
    def a(href, label, key):
        cls = "active" if active == key else ""
        return f"<a class='{cls}' href='{href}'>{html.escape(label)}</a>"
    return (
        "<div class='nav'>"
        + a("/", "WLAN-Einrichtung", "wifi")
        + a("/hotspot", "Hotspot", "hotspot")
        + a("/status", "Status", "status")
        + a("/traccar", "Traccar Client", "traccar")
        + a("/wg", "WG-VPN", "wg")
        + a("/logout", "Logout", "logout")
        + "</div>"
    )

def scan_wifi():
    r = run(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list"])
    nets = []
    for line in r.stdout.splitlines():
        parts = line.split(":")
        if len(parts) >= 3:
            ssid = parts[0].strip()
            sig = parts[1].strip()
            sec = parts[2].strip()
            if ssid:
                try:
                    sig_i = int(sig) if sig.isdigit() else 0
                except Exception:
                    sig_i = 0
                nets.append((ssid, sig_i, sec))
    best = {}
    for ssid, sig_i, sec in nets:
        if (ssid not in best) or (sig_i > best[ssid][0]):
            best[ssid] = (sig_i, sec)
    out = [(ssid, best[ssid][0], best[ssid][1]) for ssid in best]
    out.sort(key=lambda x: x[1], reverse=True)
    return out

def load_traccar_cfg():
    try:
        with open(CONFIG_TRACCAR, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    # normalize keys
    return {
        "device_id": str(cfg.get("device_id", "")).strip(),
        "server_url": str(cfg.get("server_url", "")).strip(),
        "interval": int(cfg.get("interval", cfg.get("send_interval_seconds", 30) or 30)),
        "min_accuracy": float(cfg.get("min_accuracy", cfg.get("min_accuracy_m", 50) or 50)),
    }

def load_traccar_state():
    try:
        with open(STATE_TRACCAR, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        state = {}
    return {
        "last_send_utc": state.get("last_send_utc"),
        "last_http_code": state.get("last_http_code"),
        "last_lat": state.get("last_lat"),
        "last_lon": state.get("last_lon"),
        "last_accuracy": state.get("last_accuracy"),
        "last_error": state.get("last_error"),
        "tracking_mode": state.get("tracking_mode"),
        "active_interval": state.get("active_interval"),
        "movement_distance_m": state.get("movement_distance_m"),
    }

def save_traccar_cfg(cfg):
    data = {
        "device_id": cfg["device_id"],
        "server_url": cfg["server_url"],
        "interval": int(cfg["interval"]),
        "min_accuracy": float(cfg["min_accuracy"]),
    }
    tmp = CONFIG_TRACCAR + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    subprocess.run(["mv", tmp, CONFIG_TRACCAR], check=False)



def load_queue_size():
    try:
        import json
        with open(QUEUE_TRACCAR, "r", encoding="utf-8") as f:
            q = json.load(f)
        if isinstance(q, list):
            return len(q)
    except Exception:
        pass
    return 0


def gps_status():
    info = {
        "fix": "unknown",
        "lat": "-",
        "lon": "-",
        "acc": "-",
        "last": "-",
        "devices": 0,
        "satellites_used": "-",
        "satellites_seen": "-",
        "raw_class": "-",
    }

    r = run(["bash", "-lc", "timeout 2 gpspipe -w -n 10 2>/dev/null"])
    lines = [line.strip() for line in (r.stdout or "").splitlines() if line.strip()]
    if not lines:
        info["fix"] = "no data"
        return info

    tpv = None
    sky = None
    devices = []

    for line in lines:
        try:
            j = json.loads(line)
        except Exception:
            continue

        cls = j.get("class")
        if cls == "TPV":
            tpv = j
        elif cls == "SKY":
            sky = j
        elif cls == "DEVICE":
            devices.append(j)

    if devices:
        info["devices"] = len(devices)

    if sky:
        sats = sky.get("satellites", [])
        if isinstance(sats, list):
            info["satellites_seen"] = len(sats)
            try:
                info["satellites_used"] = sum(1 for s in sats if isinstance(s, dict) and s.get("used"))
            except Exception:
                pass

    if not tpv:
        lastj = None
        for line in reversed(lines):
            try:
                lastj = json.loads(line)
                break
            except Exception:
                continue
        info["fix"] = "no tpv"
        if isinstance(lastj, dict):
            info["raw_class"] = lastj.get("class", "-")
        return info

    info["raw_class"] = tpv.get("class", "-")
    mode = tpv.get("mode", 0)
    info["fix"] = "no fix" if mode in (0, 1) else ("2D" if mode == 2 else "3D")
    if "lat" in tpv:
        info["lat"] = tpv["lat"]
    if "lon" in tpv:
        info["lon"] = tpv["lon"]
    if "epx" in tpv:
        info["acc"] = tpv["epx"]
    if "time" in tpv:
        info["last"] = tpv["time"]
    return info


def load_queue_meta():
    info = {
        "size": 0,
        "oldest_ts": None,
    }
    try:
        with open(QUEUE_TRACCAR, "r", encoding="utf-8") as f:
            q = json.load(f)
        if isinstance(q, list):
            info["size"] = len(q)
            if q:
                ts = q[0].get("timestamp")
                if ts is not None:
                    try:
                        info["oldest_ts"] = int(ts)
                    except Exception:
                        pass
    except Exception:
        pass
    return info


def format_age_seconds(seconds):
    try:
        seconds = int(seconds)
    except Exception:
        return "-"
    if seconds < 0:
        seconds = 0
    days = seconds // 86400
    seconds %= 86400
    hours = seconds // 3600
    seconds %= 3600
    mins = seconds // 60
    secs = seconds % 60
    if days > 0:
        return f"{days}d {hours}h {mins}m"
    if hours > 0:
        return f"{hours}h {mins}m"
    if mins > 0:
        return f"{mins}m {secs}s"
    return f"{secs}s"


def gps_watchdog(gps):
    info = {
        "status": "unbekannt",
        "age": "-",
    }

    ts = gps.get("time")
    if not ts or ts == "-":
        info["status"] = "keine GPS-Zeit"
        return info

    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        age = int((datetime.now(timezone.utc) - dt).total_seconds())
        info["age"] = format_age_seconds(age)
        if age <= 60:
            info["status"] = "ok"
        elif age <= 300:
            info["status"] = "alt"
        else:
            info["status"] = "Watchdog"
    except Exception:
        info["status"] = "GPS-Zeit ungültig"

    return info


def system_health():
    info = {
        "cpu_temp_c": "-",
        "load": "-",
        "ram": "-",
        "uptime": "-",
    }

    try:
        t = Path("/sys/class/thermal/thermal_zone0/temp").read_text(encoding="utf-8").strip()
        if t.isdigit():
            info["cpu_temp_c"] = f"{int(t)/1000:.1f} °C"
    except Exception:
        pass

    try:
        load = Path("/proc/loadavg").read_text(encoding="utf-8").split()[:3]
        if len(load) == 3:
            info["load"] = " / ".join(load)
    except Exception:
        pass

    try:
        mem = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            mem[k.strip()] = v.strip()
        total = int(mem["MemTotal"].split()[0])
        avail = int(mem["MemAvailable"].split()[0])
        used = total - avail
        used_mb = used // 1024
        total_mb = total // 1024
        pct = int(round((used / total) * 100))
        info["ram"] = f"{used_mb} / {total_mb} MB ({pct}%)"
    except Exception:
        pass

    try:
        up = float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
        info["uptime"] = format_age_seconds(int(up))
    except Exception:
        pass

    return info


def wifi_connected():
    r = run(["nmcli", "-t", "-f", "DEVICE,STATE", "dev"])
    for line in r.stdout.splitlines():
        parts = line.split(":")
        if len(parts) >= 2 and parts[0] == "wlan0":
            return parts[1] == "connected"
    return False


def current_wifi_ssid():
    r = run(["nmcli", "-t", "-f", "DEVICE,CONNECTION", "dev"])
    for line in r.stdout.splitlines():
        parts = line.split(":", 1)
        if len(parts) >= 2 and parts[0] == "wlan0":
            ssid = parts[1].strip()
            if ssid and ssid != "--":
                return ssid
    return None


def load_hotspot_cfg():
    cfg = {
        "ssid": "traccar-hotspot",
        "psk": "",
        "security": "open",
    }
    try:
        current = None
        for line in Path("/etc/NetworkManager/system-connections/van-hotspot.nmconnection").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                current = line[1:-1].strip().lower()
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip().lower()
            v = v.strip()
            if current == "wifi" and k == "ssid":
                cfg["ssid"] = v
            elif current == "wifi-security" and k == "psk":
                cfg["psk"] = v
            elif current == "wifi-security" and k == "key-mgmt":
                cfg["security"] = "wpa-psk" if v == "wpa-psk" else "open"
    except Exception:
        pass
    return cfg


def save_hotspot_cfg(ssid, psk, security):
    path = Path("/etc/NetworkManager/system-connections/van-hotspot.nmconnection")
    lines = path.read_text(encoding="utf-8").splitlines()
    out = []
    current = None
    wifi_done = False
    sec_done = False
    section_seen = False

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("[") and stripped.endswith("]"):
            if current == "wifi" and not wifi_done:
                out.append(f"ssid={ssid}")
                wifi_done = True

            if current == "wifi-security" and not sec_done:
                if security == "wpa-psk":
                    out.append("key-mgmt=wpa-psk")
                    out.append(f"psk={psk}")
                sec_done = True

            current = stripped[1:-1].strip().lower()
            if current == "wifi-security":
                section_seen = True
                if security == "open":
                    continue

            out.append(line)
            continue

        if current == "wifi" and stripped.startswith("ssid="):
            if not wifi_done:
                out.append(f"ssid={ssid}")
                wifi_done = True
            continue

        if current == "wifi-security":
            if stripped.startswith("key-mgmt=") or stripped.startswith("psk=") or stripped.startswith("wep-"):
                continue
            if security == "open":
                continue

        out.append(line)

    if current == "wifi" and not wifi_done:
        out.append(f"ssid={ssid}")

    if security == "wpa-psk":
        if not section_seen:
            out.append("[wifi-security]")
        if not sec_done:
            out.append("key-mgmt=wpa-psk")
            out.append(f"psk={psk}")

    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    run(["chmod", "600", str(path)])
    run(["nmcli", "connection", "reload"])
    active = hotspot_active()
    if active:
        run(["nmcli", "connection", "down", "van-hotspot"])
        run(["nmcli", "connection", "up", "van-hotspot"])


def hotspot_active():
    r = run(["nmcli", "-t", "-f", "NAME", "connection", "show", "--active"])
    for line in r.stdout.splitlines():
        if line.strip() == "van-hotspot":
            return True
    return False



def sender_control(action):
    if action not in ["start", "stop", "restart"]:
        return False
    run(["systemctl", action, "van-traccar-sender.service"])
    return True


def sender_manual_send():
    r = subprocess.run(
        ["/usr/bin/python3", "-c", "import sys; sys.path.insert(0, '/opt/van-traccar'); import sender; raise SystemExit(0 if sender.send_current_position_once() else 1)"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return r.returncode == 0, (r.stderr or r.stdout or "").strip()




def wg_control(action):
    if action not in ["start", "stop", "restart"]:
        return False
    run(["systemctl", action, "wg-quick@wg0"])
    return True


def load_wg_raw():
    try:
        return Path(WG_CONF).read_text(encoding="utf-8")
    except Exception:
        return ""


def save_wg_raw(text):
    tmp = WG_CONF + ".tmp"
    Path(tmp).write_text(text.rstrip() + "\n", encoding="utf-8")
    Path(tmp).chmod(0o600)
    subprocess.run(["mv", tmp, WG_CONF], check=False)


def wg_generate_keypair():
    priv = subprocess.run(["wg", "genkey"], capture_output=True, text=True, check=True).stdout.strip()
    pub = subprocess.run(["wg", "pubkey"], input=priv + "\n", capture_output=True, text=True, check=True).stdout.strip()
    return {"private": priv, "public": pub}


def load_wg_struct():
    data = {
        "private_key": "",
        "address": "",
        "dns": "",
        "public_key": "",
        "endpoint": "",
        "allowed_ips": "",
        "persistent_keepalive": "",
    }

    section = None
    for raw_line in load_wg_raw().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().lower()
            continue
        if "=" not in line:
            continue

        k, v = [x.strip() for x in line.split("=", 1)]
        kl = k.lower()

        if section == "interface":
            if kl == "privatekey":
                data["private_key"] = v
            elif kl == "address":
                data["address"] = v
            elif kl == "dns":
                data["dns"] = v

        elif section == "peer":
            if kl == "publickey":
                data["public_key"] = v
            elif kl == "endpoint":
                data["endpoint"] = v
            elif kl == "allowedips":
                data["allowed_ips"] = v
            elif kl == "persistentkeepalive":
                data["persistent_keepalive"] = v

    return data



def save_wg_struct(cfg):
    text = (
        "[Interface]\n"
        f"PrivateKey = {cfg['private_key'].strip()}\n"
        f"Address = {cfg['address'].strip()}\n"
        + (f"DNS = {cfg['dns'].strip()}\n" if str(cfg.get('dns', '')).strip() else "")
        + "\n"
        + "[Peer]\n"
        f"PublicKey = {cfg['public_key'].strip()}\n"
        f"Endpoint = {cfg['endpoint'].strip()}\n"
        f"AllowedIPs = {cfg['allowed_ips'].strip()}\n"
        + (f"PersistentKeepalive = {str(cfg.get('persistent_keepalive', '')).strip()}\n" if str(cfg.get('persistent_keepalive', '')).strip() else "")
    )
    save_wg_raw(text)


def wg_endpoint_host(endpoint):
    ep = str(endpoint or "").strip()
    if not ep:
        return ""
    if ep.startswith("[") and "]:" in ep:
        return ep[1:].split("]:", 1)[0].strip()
    if ep.count(":") == 1:
        return ep.rsplit(":", 1)[0].strip()
    return ep


def wg_resolve_endpoint_ip(endpoint):
    host = wg_endpoint_host(endpoint)
    if not host:
        return "-"
    rc, out, err = _run(["getent", "ahostsv4", host])
    if rc == 0 and out:
        for line in out.splitlines():
            parts = line.split()
            if parts:
                return parts[0].strip()
    return "-"


def wg_transfer():
    info = {"rx": "-", "tx": "-"}
    rc, out, err = _run(["wg", "show", "wg0", "transfer"])
    if rc != 0 or not out:
        return info
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            info["rx"] = parts[1].strip()
            info["tx"] = parts[2].strip()
            break
    return info


def wg_latest_handshake():
    info = {
        "epoch": None,
        "age_text": "-",
        "status": "unbekannt",
    }

    rc, out, err = _run(["wg", "show", "wg0", "latest-handshakes"])
    if rc != 0 or not out:
        info["status"] = "kein Tunnel"
        return info

    ts = None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            try:
                ts = int(parts[1].strip())
                break
            except Exception:
                pass

    if ts is None:
        info["status"] = "kein Handshake"
        return info

    if ts == 0:
        info["epoch"] = 0
        info["age_text"] = "nie"
        info["status"] = "kein Handshake"
        return info

    info["epoch"] = ts
    try:
        age = int(time.time()) - ts
        if age < 0:
            age = 0
        info["age_text"] = format_age_seconds(age)
        if age <= 90:
            info["status"] = "frisch"
        elif age <= 300:
            info["status"] = "alt"
        else:
            info["status"] = "kritisch"
    except Exception:
        info["status"] = "unbekannt"

    return info


@app.route("/setup", methods=["GET", "POST"])
def setup():
    if is_auth_configured():
        return redirect(url_for("login"), code=303)

    error = ""
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        password2 = request.form.get("password2") or ""
        reset_pin = (request.form.get("reset_pin") or "").strip()

        if not username or not password or not password2 or not reset_pin:
            error = "Bitte alle Felder ausfüllen."
        elif password != password2:
            error = "Die Passwörter stimmen nicht überein."
        elif len(password) < 8:
            error = "Das Passwort muss mindestens 8 Zeichen lang sein."
        elif len(reset_pin) < 4:
            error = "Die Reset-PIN muss mindestens 4 Zeichen lang sein."
        else:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            data = load_auth()
            data["username"] = username
            data["password_hash"] = generate_password_hash(password)
            data["reset_pin_hash"] = generate_password_hash(reset_pin)
            data["failed_reset_attempts"] = 0
            data["reset_locked_until"] = 0
            data["failed_login_attempts"] = 0
            data["login_locked_until"] = 0
            data["created_at"] = now_str
            data["updated_at"] = now_str
            save_auth(data)
            write_audit_log(f"{username} completed initial panel setup")
            return redirect(url_for("login"), code=303)

    body = (
        "<h1 class='h1'>Panel-Ersteinrichtung</h1>"
        "<p class='small'>Es ist noch kein Panel-Zugang eingerichtet.</p>"
        "<form method='post'>"
        "<label>Benutzername</label>"
        "<input type='text' name='username' required>"
        "<label>Passwort</label>"
        "<input type='password' name='password' required>"
        "<label>Passwort wiederholen</label>"
        "<input type='password' name='password2' required>"
        "<label>Reset-PIN</label>"
        "<input type='password' name='reset_pin' required>"
        "<div class='notice'>Die Reset-PIN wird benötigt, um den Panel-Zugang zurückzusetzen. Traccar-, WLAN-, Hotspot- und WireGuard-Konfigurationen bleiben dabei erhalten.</div>"
        "<div class='small'>Die Sitzung läuft nach 20 Minuten Inaktivität automatisch ab.</div>"
        "<div style='margin-top:12px'><button class='btn' type='submit'>Einrichtung abschließen</button></div>"
        + (f"<div class='notice err'>{html.escape(error)}</div>" if error else "")
        + "</form>"
    )
    return public_page(body, title="Panel-Ersteinrichtung")


@app.route("/login", methods=["GET", "POST"])
def login():
    if not is_auth_configured():
        return redirect(url_for("setup"), code=303)

    if is_session_valid():
        return redirect(url_for("status_page"), code=303)

    error = ""
    info = ""
    auth = load_auth()
    now_ts = int(time.time())
    locked_until = int(auth.get("login_locked_until", 0) or 0)

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        if locked_until > now_ts:
            remaining = locked_until - now_ts
            minutes = max(1, (remaining + 59) // 60)
            info = f"Login ist aktuell gesperrt. Erneut versuchen in ca. {minutes} Minute(n)."
        elif not username or not password:
            error = "Bitte Benutzername und Passwort eingeben."
        elif username == auth.get("username") and check_password_hash(auth.get("password_hash", ""), password):
            auth["failed_login_attempts"] = 0
            auth["login_locked_until"] = 0
            save_auth(auth)

            session.clear()
            session["logged_in"] = True
            session["username"] = username
            session["last_seen"] = int(time.time())
            session.permanent = False
            write_audit_log(f"{username} logged in")
            return redirect(url_for("status_page"), code=303)
        else:
            attempts = int(auth.get("failed_login_attempts", 0) or 0) + 1
            auth["failed_login_attempts"] = attempts

            if attempts >= LOGIN_MAX_ATTEMPTS:
                auth["login_locked_until"] = now_ts + LOGIN_LOCK_SECONDS
                auth["failed_login_attempts"] = 0
                save_auth(auth)
                write_audit_log(f"login locked after too many invalid attempts for username={username or 'empty'}")
            else:
                save_auth(auth)
                write_audit_log(f"invalid login attempt for username={username or 'empty'}")
                error = f"Ungültiger Benutzername oder Passwort. Verbleibende Versuche: {LOGIN_MAX_ATTEMPTS - attempts}"

        auth = load_auth()
        locked_until = int(auth.get("login_locked_until", 0) or 0)

    if locked_until > now_ts and not info:
        remaining = locked_until - now_ts
        minutes = max(1, (remaining + 59) // 60)
        info = f"Login ist aktuell gesperrt. Erneut versuchen in ca. {minutes} Minute(n)."

    body = (
        "<h1 class='h1'>Login</h1>"
        "<form method='post'>"
        "<label>Benutzername</label>"
        "<input type='text' name='username' required>"
        "<label>Passwort</label>"
        "<input type='password' name='password' required>"
        "<div class='small'>Die Sitzung läuft nach 20 Minuten Inaktivität automatisch ab.</div>"
        "<div style='margin-top:12px;display:flex;gap:10px;flex-wrap:wrap'>"
        "<button class='btn' type='submit'>Anmelden</button>"
        "<a class='btn' href='/reset-access'>Zugang zurücksetzen</a>"
        "</div>"
        + (f"<div class='notice'>{html.escape(info)}</div>" if info else "")
        + (f"<div class='notice err'>{html.escape(error)}</div>" if error else "")
        + "</form>"
    )
    return public_page(body, title="Login")


@app.route("/logout")
def logout():
    username = session.get("username", "unknown")
    session.clear()
    write_audit_log(f"{username} logged out")
    return redirect(url_for("login"), code=303)


@app.route("/reset-access", methods=["GET", "POST"])
def reset_access():
    if not is_auth_configured():
        return redirect(url_for("setup"), code=303)

    error = ""
    info = ""
    warning = ""
    auth = load_auth()
    now_ts = int(time.time())
    locked_until = int(auth.get("reset_locked_until", 0) or 0)
    failed_attempts = int(auth.get("failed_reset_attempts", 0) or 0)
    show_factory_reset = failed_attempts >= 3 or locked_until > now_ts

    if request.method == "POST":
        reset_pin = (request.form.get("reset_pin") or "").strip()
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        password2 = request.form.get("password2") or ""

        if locked_until > now_ts:
            remaining = locked_until - now_ts
            minutes = max(1, (remaining + 59) // 60)
            info = f"Reset-Zugang ist aktuell gesperrt. Erneut versuchen in ca. {minutes} Minute(n)."
        elif not reset_pin or not username or not password or not password2:
            error = "Bitte alle Felder ausfüllen."
        elif password != password2:
            error = "Die Passwörter stimmen nicht überein."
        elif len(password) < 8:
            error = "Das Passwort muss mindestens 8 Zeichen lang sein."
        elif len(reset_pin) < 4:
            error = "Die Reset-PIN ist ungültig."
        elif not check_password_hash(auth.get("reset_pin_hash", ""), reset_pin):
            attempts = int(auth.get("failed_reset_attempts", 0) or 0) + 1
            auth["failed_reset_attempts"] = attempts
            show_factory_reset = attempts >= 3

            if attempts >= RESET_PIN_MAX_ATTEMPTS:
                auth["reset_locked_until"] = now_ts + RESET_PIN_LOCK_SECONDS
                auth["failed_reset_attempts"] = 0
                save_auth(auth)
                write_audit_log("reset access locked after too many invalid reset PIN attempts")
                remaining = RESET_PIN_LOCK_SECONDS
                minutes = max(1, (remaining + 59) // 60)
                info = f"Reset-Zugang ist aktuell gesperrt. Erneut versuchen in ca. {minutes} Minute(n)."
            else:
                save_auth(auth)
                write_audit_log("invalid reset PIN attempt")
                error = f"Ungültige Reset-PIN. Verbleibende Versuche: {RESET_PIN_MAX_ATTEMPTS - attempts}"

            if show_factory_reset:
                warning = "Die Reset-PIN wurde mehrfach falsch eingegeben. Falls die PIN nicht mehr bekannt ist, kann ein Werksreset durchgeführt werden. Dabei werden nur die Panel-Zugangsdaten gelöscht. Traccar-, WLAN-, Hotspot- und WireGuard-Konfigurationen bleiben erhalten."
        else:
            auth["username"] = username
            auth["password_hash"] = generate_password_hash(password)
            auth["failed_reset_attempts"] = 0
            auth["reset_locked_until"] = 0
            auth["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_auth(auth)
            session.clear()
            write_audit_log(f"{username} reset panel access via reset PIN")
            return redirect(url_for("login"), code=303)

        auth = load_auth()
        locked_until = int(auth.get("reset_locked_until", 0) or 0)
        failed_attempts = int(auth.get("failed_reset_attempts", 0) or 0)
        show_factory_reset = show_factory_reset or failed_attempts >= 3

    if locked_until > now_ts and not info:
        remaining = locked_until - now_ts
        minutes = max(1, (remaining + 59) // 60)
        info = f"Reset-Zugang ist aktuell gesperrt. Erneut versuchen in ca. {minutes} Minute(n)."

    if show_factory_reset and not warning:
        warning = "Die Reset-PIN wurde mehrfach falsch eingegeben. Falls die PIN nicht mehr bekannt ist, kann ein Werksreset durchgeführt werden. Dabei werden nur die Panel-Zugangsdaten gelöscht. Traccar-, WLAN-, Hotspot- und WireGuard-Konfigurationen bleiben erhalten."

    factory_reset_html = ""
    if show_factory_reset:
        factory_reset_html = (
            "<div class='notice err'>"
            + html.escape(warning)
            + "<div style='margin-top:12px'><a class='btn' href='/factory-reset'>Werksreset</a></div>"
            + "</div>"
        )

    body = (
        "<h1 class='h1'>Zugang zurücksetzen</h1>"
        "<p class='small'>Mit der Reset-PIN können Benutzername und Passwort des Panels zurückgesetzt werden.</p>"
        "<form method='post'>"
        "<label>Reset-PIN</label>"
        "<input type='password' name='reset_pin' required>"
        "<label>Neuer Benutzername</label>"
        "<input type='text' name='username' required>"
        "<label>Neues Passwort</label>"
        "<input type='password' name='password' required>"
        "<label>Neues Passwort wiederholen</label>"
        "<input type='password' name='password2' required>"
        "<div style='margin-top:12px;display:flex;gap:10px;flex-wrap:wrap'>"
        "<button class='btn' type='submit'>Zugang zurücksetzen</button>"
        "<a class='btn' href='/login'>Zurück</a>"
        "</div>"
        + (f"<div class='notice'>{html.escape(info)}</div>" if info else "")
        + (f"<div class='notice err'>{html.escape(error)}</div>" if error else "")
        + factory_reset_html
        + "</form>"
    )
    return public_page(body, title="Zugang zurücksetzen")


@app.route("/factory-reset", methods=["GET", "POST"])
def factory_reset():
    if not is_auth_configured():
        return redirect(url_for("setup"), code=303)

    auth = load_auth()
    failed_attempts = int(auth.get("failed_reset_attempts", 0) or 0)
    locked_until = int(auth.get("reset_locked_until", 0) or 0)
    now_ts = int(time.time())

    if failed_attempts < 3 and locked_until <= now_ts:
        return redirect(url_for("reset_access"), code=303)

    confirm_text = "WERKSRESET"
    error = ""

    if request.method == "POST":
        entered = (request.form.get("confirm_text") or "").strip()
        if entered != confirm_text:
            error = "Bestätigungstext stimmt nicht überein."
        else:
            try:
                if AUTH_FILE.exists():
                    AUTH_FILE.unlink()
            except Exception:
                pass

            try:
                if SECRET_FILE.exists():
                    SECRET_FILE.unlink()
            except Exception:
                pass

            session.clear()
            return redirect(url_for("setup"), code=303)

    body = (
        "<h1 class='h1'>Werksreset</h1>"
        "<div class='notice err'>"
        "Achtung: Beim Werksreset werden die Zugangsdaten des Panels gelöscht. "
        "Traccar-, WLAN-, Hotspot- und WireGuard-Konfigurationen bleiben erhalten."
        "</div>"
        "<p class='small'>Gib zur Bestätigung exakt folgenden Text ein:</p>"
        f"<div class='notice mono'>{confirm_text}</div>"
        "<form method='post'>"
        "<label>Bestätigung</label>"
        "<input type='text' name='confirm_text' required>"
        "<div style='margin-top:12px;display:flex;gap:10px;flex-wrap:wrap'>"
        "<button class='btn' type='submit'>Werksreset ausführen</button>"
        "<a class='btn' href='/reset-access'>Abbrechen</a>"
        "</div>"
        + (f"<div class='notice err'>{html.escape(error)}</div>" if error else "")
        + "</form>"
    )
    return public_page(body, title="Werksreset")

@app.route("/")
def index():
    nets = scan_wifi()
    wifi_ok = wifi_connected()
    wifi_ssid = current_wifi_ssid()
    hotspot_ok = hotspot_active()
    hotspot_cfg = load_hotspot_cfg()
    sender = _sender_status()
    vpn = _vpn_status()

    rows = ""
    for ssid, sig, sec in nets:
        ssid_q = quote(ssid, safe="")
        sec_txt = sec if sec else "open/unknown"
        width = max(0, min(100, sig))
        rows += (
            "<tr class='row'>"
            f"<td class='ssid'>{html.escape(ssid)}</td>"
            f"<td class='sig'><div class='bar'><div class='fill' style='width:{width}%'></div></div>"
            f"<div class='small mono'>{sig}%</div></td>"
            f"<td><span class='pill'>{html.escape(sec_txt)}</span></td>"
            f"<td style='text-align:right'><a class='btn' href='/connect?ssid={ssid_q}'>Verbinden</a></td>"
            "</tr>"
        )

    status_box = (
        "<div class='card' style='margin-bottom:14px'>"
        + "<div class='header'>"
        + "<h1 class='h1'>Status</h1>"
        + "<span class='badge'>Diagnose</span>"
        + "</div>"
        + "<div class='grid'>"
        + f"<div class='card kpi'><p class='title'>WLAN</p><p class='value'>{'verbunden' if wifi_ok else 'nicht verbunden'}</p></div>"
        + f"<div class='card kpi'><p class='title'>Hotspot</p><p class='value'>{'aktiv' if hotspot_ok else 'inaktiv'}</p></div>"
        + f"<div class='card kpi'><p class='title'>Sender</p><p class='value'>{html.escape(sender['state'])}</p></div>"
        + f"<div class='card kpi'><p class='title'>VPN</p><p class='value'>{html.escape(vpn['state'])}</p></div>"
        + "</div>"
        + "</div>"
    )

    body = (
        nav("wifi")
        + status_box
        + "<div class='card'>"
        + "<div class='header'>"
        + "<h1 class='h1'>WLAN-Einrichtung</h1>"
        + f"<span class='badge'>{html.escape('WLAN: ' + wifi_ssid) if wifi_ssid else 'Kein WLAN verbunden'} &nbsp;|&nbsp; Hotspot: {html.escape(hotspot_cfg['ssid'])} → Panel: http://10.42.0.1</span>"
        + "</div>"
        + "<p class='small'>WLAN auswählen, Passwort eingeben, speichern. Der Pi versucht danach sofort zu verbinden.</p>"
        + "<div class='hr'></div>"
        + "<table class='table'>"
        + (rows if rows else "<tr><td class=small>Keine WLANs gefunden. Standort/Empfang prüfen.</td></tr>")
        + "</table>"
        + "</div>"
    )
    return html_page(body, title="WLAN-Einrichtung")


@app.route("/hotspot")
def hotspot_page():
    cfg = load_hotspot_cfg()
    info = ""
    if request.args.get("saved") == "1":
        info = "<div class='notice ok'>Hotspot-Konfiguration gespeichert.</div>"

    warn_open = ""
    if cfg.get("security") == "open":
        warn_open = "<div class='notice err'>⚠ Setup-Hotspot ist ungesichert. Bitte Passwort setzen.</div>"

    sec_open_selected = "selected" if cfg.get("security") == "open" else ""
    sec_wpa_selected = "selected" if cfg.get("security") == "wpa-psk" else ""
    password_hint = "leer lassen für offenen Setup-Hotspot" if cfg.get("security") == "open" else "mindestens 8 Zeichen für WPA2-PSK"

    body = (
        nav("hotspot")
        + "<div class='card'>"
        + "<div class='header'>"
        + "<h1 class='h1'>Hotspot</h1>"
        + "<span class='badge'>Access Point auf wlan0 / Panel: http://10.42.0.1</span>"
        + "</div>"
        + info
        + warn_open
        + "<form method='post' action='/hotspot/save'>"
        + "<div class='small'>SSID</div>"
        + f"<div style='margin-top:8px'><input type='text' name='ssid' value='{html.escape(cfg['ssid'])}' maxlength='32' required></div>"
        + "<div class='small' style='margin-top:14px'>Sicherheit</div>"
        + "<div style='margin-top:8px'><select name='security' class='btn' style='width:100%;max-width:520px'>"
        + f"<option value='open' {sec_open_selected}>Offen (ohne Passwort)</option>"
        + f"<option value='wpa-psk' {sec_wpa_selected}>WPA2-PSK</option>"
        + "</select></div>"
        + f"<div class='small' style='margin-top:14px'>Passwort ({html.escape(password_hint)})</div>"
        + f"<div style='margin-top:8px'><input type='text' name='password' value='{html.escape(cfg['psk'])}'></div>"
        + "<div style='margin-top:12px'><button class='btn' type='submit'>Speichern</button></div>"
        + "</form>"
        + "<div class='notice'>Hinweis: Wenn der Hotspot gerade aktiv ist, wird er mit den neuen Werten neu gestartet.</div>"
        + "</div>"
    )
    return html_page(body, title="Hotspot")


@app.route("/hotspot/save", methods=["POST"])
def hotspot_save():
    ssid = request.form.get("ssid", "").strip()
    password = request.form.get("password", "").strip()
    security = request.form.get("security", "open").strip()

    if not ssid:
        return html_page(nav("hotspot") + "<div class='card'><div class='notice err'>Fehler: SSID fehlt.</div></div>", title="Hotspot"), 400
    if security not in ("open", "wpa-psk"):
        return html_page(nav("hotspot") + "<div class='card'><div class='notice err'>Fehler: Ungültige Sicherheitsoption.</div></div>", title="Hotspot"), 400
    if security == "wpa-psk" and len(password) < 8:
        return html_page(nav("hotspot") + "<div class='card'><div class='notice err'>Fehler: Passwort muss mindestens 8 Zeichen lang sein.</div></div>", title="Hotspot"), 400

    save_hotspot_cfg(ssid, password, security)
    return redirect("/hotspot?saved=1")


@app.route("/connect")
def connect():
    ssid = request.args.get("ssid", "")
    ssid = unquote(ssid)
    if not ssid:
        return html_page(nav("wifi") + "<div class='card'><div class='notice err'>Fehler: SSID fehlt.</div></div>"), 400

    body = (
        nav("wifi")
        + "<div class='card'>"
        + f"<div class='header'><h1 class='h1'>Verbinden: <span class='mono'>{html.escape(ssid)}</span></h1>"
        + "<a class='btn' href='/'>Zurück</a></div>"
        + "<form method='post' action='/save'>"
        + f"<input type='hidden' name='ssid' value='{html.escape(ssid)}'>"
        + "<div class='small'>Passwort (WPA/WPA2/WPA3):</div>"
        + "<div style='margin-top:8px'><input type='password' name='password' autocomplete='current-password' autofocus></div>"
        + "<div style='margin-top:12px'><button class='btn' type='submit'>Speichern & verbinden</button></div>"
        + "</form>"
        + "<div class='notice'>Hinweis: Bei falschem Passwort bleibt der Pi im Hotspot. Dann einfach erneut verbinden.</div>"
        + "</div>"
    )
    return html_page(body, title=f"Verbinden: {ssid}")

@app.route("/save", methods=["POST"])
def save():
    ssid = request.form.get("ssid", "").strip()
    password = request.form.get("password", "")
    if not ssid:
        return html_page(nav("wifi") + "<div class='card'><div class='notice err'>Fehler: SSID fehlt.</div></div>"), 400

    run(["nmcli", "connection", "delete", ssid])

    add = run([
        "nmcli", "connection", "add",
        "type", "wifi",
        "ifname", "wlan0",
        "con-name", ssid,
        "ssid", ssid,
        "wifi-sec.key-mgmt", "wpa-psk",
        "wifi-sec.psk", password
    ])

    up = run(["nmcli", "connection", "up", ssid])

    ok = (up.returncode == 0)
    if ok:
        msg = f"<div class='notice ok'>Verbindungsversuch zu <b>{html.escape(ssid)}</b> gestartet. Wenn erfolgreich, ist der Pi im neuen WLAN erreichbar.</div>"
    else:
        msg = (
            f"<div class='notice err'>Verbindung zu <b>{html.escape(ssid)}</b> fehlgeschlagen.</div>"
            f"<div class='notice'><div class='small mono'>nmcli add: rc={add.returncode} | nmcli up: rc={up.returncode}</div>"
            f"<div class='small mono'>{html.escape((up.stderr or up.stdout or '').strip())}</div></div>"
        )

    body = (
        nav("wifi")
        + "<div class='card'>"
        + "<div class='header'><h1 class='h1'>Status</h1>"
        + "<a class='btn' href='/'>Zurück zur Liste</a></div>"
        + msg
        + "</div>"
    )
    return html_page(body, title="Status")

@app.route("/traccar/control", methods=["POST"])
def traccar_control():
    action = request.form.get("action", "").strip().lower()
    if action not in ["start", "stop", "restart", "manual-send"]:
        body = nav("traccar") + "<div class='card'><div class='notice err'>Ungültige Aktion.</div><a class='btn' href='/traccar'>Zurück</a></div>"
        return html_page(body, title="Fehler"), 400

    if action == "manual-send":
        ok, msg = sender_manual_send()
        body = (
            nav("traccar")
            + "<div class='card'>"
            + (f"<div class='notice ok'>Aktuelle Position manuell gesendet.</div>" if ok else f"<div class='notice err'>Manuelles Senden fehlgeschlagen.</div>")
            + (f"<div class='notice'><div class='small mono'>{html.escape(msg)}</div></div>" if msg else "")
            + "<a class='btn' href='/traccar'>Zurück</a>"
            + "</div>"
        )
        return html_page(body, title="Sender-Steuerung")

    sender_control(action)

    body = (
        nav("traccar")
        + "<div class='card'>"
        + f"<div class='notice ok'>Sender-Aktion ausgeführt: {html.escape(action)}</div>"
        + "<a class='btn' href='/traccar'>Zurück</a>"
        + "</div>"
    )
    return html_page(body, title="Sender-Steuerung")

@app.route("/traccar")
def traccar():
    cfg = load_traccar_cfg()
    gps = gps_status()

    body = (
        nav("traccar")
        + "<div class='card'>"
        + "<div class='header'><h1 class='h1'>Traccar Client</h1>"
        + "<span class='badge'>WLAN-only (soll nicht im Hotspot genutzt werden)</span></div>"
        + "<p class='small'>Einstellungen für den Traccar Client Sender. Änderungen werden in <span class='mono'>/opt/van-traccar/config.json</span> gespeichert.</p>"
        + "<div class='hr'></div>"
        + "<div class='grid'>"
        + f"<div class='card kpi'><p class='title'>Fix</p><p class='value'>{html.escape(str(gps['fix']))}</p></div>"
        + f"<div class='card kpi'><p class='title'>Letzter TPV</p><p class='value mono'>{html.escape(str(gps['last']))}</p></div>"
        + f"<div class='card kpi'><p class='title'>Latitude</p><p class='value mono'>{html.escape(str(gps['lat']))}</p></div>"
        + f"<div class='card kpi'><p class='title'>Longitude</p><p class='value mono'>{html.escape(str(gps['lon']))}</p></div>"
        + f"<div class='card kpi'><p class='title'>Accuracy (epx)</p><p class='value mono'>{html.escape(str(gps['acc']))}</p></div>"
        + f"<div class='card kpi'><p class='title'>Aktuelle Config</p><p class='value mono'>id={html.escape(cfg['device_id'])}</p><p class='small mono'>url={html.escape(cfg['server_url'])}</p></div>"
        + "</div>"
        + "<div class='hr'></div>"
        + "<form method='post' action='/traccar/save'>"
        + "<label>Server URL</label>"
        + f"<input type='text' name='server_url' value='{html.escape(cfg['server_url'])}' placeholder='https://traccar.example.com/'>"
        + f"<div class='small'>Aktuell: <span class='mono'>{html.escape(cfg['server_url'])}</span></div>"
        + "<label>Device ID (Identifier)</label>"
        + f"<input type='text' name='device_id' value='{html.escape(cfg['device_id'])}' placeholder='00000001'>"
        + f"<div class='small'>Aktuell: <span class='mono'>{html.escape(cfg['device_id'])}</span></div>"
        + "<label>Sendeintervall (Sekunden)</label>"
        + f"<input type='number' name='interval' min='5' max='3600' step='1' value='{html.escape(str(cfg['interval']))}'>"
        + f"<div class='small'>Aktuell: <span class='mono'>{html.escape(str(cfg['interval']))}</span></div>"
        + "<label>Min. Accuracy (Meter) – nur senden, wenn epx ≤ Wert</label>"
        + f"<input type='number' name='min_accuracy' min='1' max='9999' step='1' value='{html.escape(str(int(cfg['min_accuracy'])))}'>"
        + f"<div class='small'>Aktuell: <span class='mono'>{html.escape(str(int(cfg['min_accuracy'])))}</span></div>"
        + "<div style='margin-top:14px'><button class='btn' type='submit'>Speichern</button></div>"
        + "</form>"
        + "<div class='hr'></div>"
        + "<div style='margin-top:10px'>"
        + "<form method='post' action='/traccar/control' style='display:flex;gap:10px;flex-wrap:wrap'>"
        + "<button class='btn' name='action' value='start'>Sender starten</button>"
        + "<button class='btn' name='action' value='stop'>Sender stoppen</button>"
        + "<button class='btn' name='action' value='restart'>Sender neu starten</button>"
        + "<button class='btn' name='action' value='manual-send'>Aktuelle Position manuell senden</button>"
        + "</form>"
        + "</div>"
        + "</div>"
    )
    return html_page(body, title="Traccar Client")

@app.route("/traccar/save", methods=["POST"])
def traccar_save():
    cfg = load_traccar_cfg()

    server_url = request.form.get("server_url", "").strip()
    device_id = request.form.get("device_id", "").strip()
    interval = request.form.get("interval", "").strip()
    min_accuracy = request.form.get("min_accuracy", "").strip()

    # validate
    err = []
    if not server_url.startswith("http://") and not server_url.startswith("https://"):
        err.append("server_url muss mit http:// oder https:// beginnen")
    if not device_id:
        err.append("device_id darf nicht leer sein")
    try:
        interval_i = int(interval)
        if interval_i < 5 or interval_i > 3600:
            err.append("interval muss 5..3600 sein")
    except Exception:
        err.append("interval ist ungültig")
        interval_i = cfg["interval"]

    try:
        min_acc_i = float(min_accuracy)
        if min_acc_i < 1 or min_acc_i > 9999:
            err.append("min_accuracy muss 1..9999 sein")
    except Exception:
        err.append("min_accuracy ist ungültig")
        min_acc_i = cfg["min_accuracy"]

    if err:
        body = nav("traccar") + "<div class='card'><div class='notice err'>" + "<br>".join(map(html.escape, err)) + "</div><a class='btn' href='/traccar'>Zurück</a></div>"
        return html_page(body, title="Fehler"), 400

    cfg["server_url"] = server_url
    cfg["device_id"] = device_id
    cfg["interval"] = interval_i
    cfg["min_accuracy"] = min_acc_i

    # write atomically (no sudo needed when running as root service)
    tmp = CONFIG_TRACCAR + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    subprocess.run(["mv", tmp, CONFIG_TRACCAR], check=False)

    body = nav("traccar") + "<div class='card'><div class='notice ok'>Gespeichert.</div><a class='btn' href='/traccar'>Zurück</a></div>"
    return html_page(body, title="Gespeichert")

# --- Smart Van: Status Endpoint (/status) ---
import json, subprocess, time
from datetime import datetime, timezone

def _run(cmd, timeout=4):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"

def _internet_ok():
    rc, _, _ = _run(["curl", "-fsS", "-m", "4", "https://example.com/"])
    return rc == 0

def _vpn_status():
    rc, out, err = _run(["systemctl", "is-active", "wg-quick@wg0"])
    if rc == 0:
        return {"active": True, "state": out}
    return {"active": False, "state": out or err or "inactive"}

def _sender_status():
    rc, out, err = _run(["systemctl", "is-active", "van-traccar-sender.service"])
    active = (rc == 0 and out.strip() == "active")
    return {"active": active, "state": out or err}

def _gps_status():
    # gpsd JSON: when no device attached you will usually only see VERSION/DEVICES/WATCH
    rc, out, err = _run(["timeout", "2", "gpspipe", "-w"], timeout=3)
    devices = []
    tpv = {}
    sky = {}
    if out:
        for line in out.splitlines():
            try:
                j = json.loads(line)
            except Exception:
                continue
            cls = j.get("class")
            if cls == "DEVICES":
                devices = j.get("devices", []) or []
            elif cls == "TPV":
                tpv = j
            elif cls == "SKY":
                sky = j

    # Normalize
    fix_mode = tpv.get("mode")  # 1=no fix, 2=2D, 3=3D
    sats_used = sky.get("uSat")
    sats_seen = sky.get("nSat")
    lat = tpv.get("lat")
    lon = tpv.get("lon")
    acc = tpv.get("eph")  # horizontal estimated error in meters (if present)
    t = tpv.get("time")   # ISO8601 from gpsd if present

    if fix_mode == 1:
        fix = "no fix"
    elif fix_mode == 2:
        fix = "2D"
    elif fix_mode == 3:
        fix = "3D"
    else:
        fix = None

    return {
        "devices": devices,
        "fix": fix,
        "mode": fix_mode,
        "satellites_used": sats_used,
        "satellites_seen": sats_seen,
        "lat": lat,
        "lon": lon,
        "accuracy_m": acc,
        "time": t,
        "raw_rc": rc,
        "raw_err": err,
    }


def gps_signal_quality(gps):
    try:
        fix = str(gps.get("fix") or "").strip().lower()
    except Exception:
        fix = ""

    if fix in ("", "no fix", "no data", "unknown", "none"):
        return {"percent": 0, "label": "kein Fix"}

    score = 40 if fix == "2d" else 55 if fix == "3d" else 25

    try:
        acc = float(gps.get("accuracy_m"))
    except Exception:
        acc = None

    if acc is not None:
        if acc <= 3:
            score += 35
        elif acc <= 5:
            score += 30
        elif acc <= 10:
            score += 25
        elif acc <= 20:
            score += 18
        elif acc <= 50:
            score += 10
        elif acc <= 100:
            score += 5

    try:
        used = int(gps.get("satellites_used"))
    except Exception:
        used = 0

    try:
        seen = int(gps.get("satellites_seen"))
    except Exception:
        seen = 0

    score += min(15, used * 2)
    score += min(10, seen // 2)
    score = max(0, min(100, score))

    if score >= 85:
        label = "sehr gut"
    elif score >= 70:
        label = "gut"
    elif score >= 50:
        label = "mittel"
    else:
        label = "schwach"

    return {"percent": score, "label": label}


@app.route("/status")
def status_page():
    data = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "internet_ok": _internet_ok(),
        "vpn": _vpn_status(),
        "sender": _sender_status(),
        "gps": _gps_status(),
        "wifi_connected": wifi_connected(),
        "hotspot_active": hotspot_active(),
    }
    data["sender"].setdefault("last_send_utc", None)
    data["sender"].setdefault("last_http_code", None)
    data["sender"].setdefault("note", "no telemetry yet")

    gps = data["gps"]
    sender = data["sender"]
    state = load_traccar_state()
    queue_size = load_queue_size()
    queue_meta = load_queue_meta()
    vpn = data["vpn"]
    health = system_health()
    watchdog = gps_watchdog(gps)
    signal = gps_signal_quality(gps)
    wg_traffic = wg_transfer()
    wg_handshake = wg_latest_handshake()

    body = (
        nav("wifi")
        + "<div class='card'>"
        + "<div class='header'>"
        + "<h1 class='h1'>Status</h1>"
        + "<a class='btn' href='/'>Zurück</a>"
        + "</div>"
        + "<div class='grid'>"
        + f"<div class='card kpi'><p class='title'>WLAN</p><p class='value'>{'verbunden' if data['wifi_connected'] else 'nicht verbunden'}</p></div>"
        + f"<div class='card kpi'><p class='title'>Hotspot</p><p class='value'>{'aktiv' if data['hotspot_active'] else 'inaktiv'}</p></div>"
        + f"<div class='card kpi'><p class='title'>Internet</p><p class='value'>{'ok' if data['internet_ok'] else 'kein Internet'}</p></div>"
        + f"<div class='card kpi'><p class='title'>VPN</p><p class='value'>{html.escape(str(vpn['state']))}</p><p class='small mono'>Rx: {html.escape(str(wg_traffic.get('rx', '-')))} B | Tx: {html.escape(str(wg_traffic.get('tx', '-')))} B<br>Handshake: {html.escape(str(wg_handshake.get('age_text','-')))} ({html.escape(str(wg_handshake.get('status','-')))})</p></div>"
        + f"<div class='card kpi'><p class='title'>Sender</p><p class='value'>{html.escape(str(sender['state']))}</p></div><div class='card kpi'><p class='title'>Queue</p><p class='value'>{queue_size}</p></div>"
        + f"<div class='card kpi'><p class='title'>Queue ältester Punkt</p><p class='value mono'>{html.escape(str(queue_meta['oldest_ts'] if queue_meta['oldest_ts'] is not None else '-'))}</p></div>"
        + f"<div class='card kpi'><p class='title'>Letzte Sendung</p><p class='value mono'>{html.escape(str(state['last_send_utc'] or '-'))}</p></div>"
        + f"<div class='card kpi'><p class='title'>Letzte Position</p><p class='value mono'>{html.escape(str(state['last_lat']))}, {html.escape(str(state['last_lon']))}</p></div>"
        + f"<div class='card kpi'><p class='title'>HTTP Status</p><p class='value mono'>{html.escape(str(state['last_http_code'] or '-'))}</p></div>"
        + f"<div class='card kpi'><p class='title'>Letzter Fehler</p><p class='value mono'>{html.escape(str(state['last_error'] or '-'))}</p></div>"
        + f"<div class='card kpi'><p class='title'>GPS-Fix</p><p class='value'>{html.escape(str(gps['fix'] or '-'))}</p></div>"
        + f"<div class='card kpi'><p class='title'>Breitengrad</p><p class='value mono'>{html.escape(str(gps['lat'] or '-'))}</p></div>"
        + f"<div class='card kpi'><p class='title'>Längengrad</p><p class='value mono'>{html.escape(str(gps['lon'] or '-'))}</p></div>"
        + f"<div class='card kpi'><p class='title'>GPS Accuracy</p><p class='value mono'>{html.escape(str(gps['accuracy_m'] or '-'))}</p></div>"
        + f"<div class='card kpi'><p class='title'>GPS Signalqualität</p><p class='value mono'>{signal['percent']} % ({html.escape(signal['label'])})</p></div>"
        + f"<div class='card kpi'><p class='title'>Satelliten</p><p class='value mono'>{html.escape(str(gps['satellites_used'] or '-'))} / {html.escape(str(gps['satellites_seen'] or '-'))}</p></div>"
        + f"<div class='card kpi'><p class='title'>GPS Watchdog</p><p class='value'>{html.escape(str(watchdog['status']))}</p></div>"
        + f"<div class='card kpi'><p class='title'>Letzte GPS-Zeit vor</p><p class='value mono'>{html.escape(str(watchdog['age']))}</p></div>"
        + f"<div class='card kpi'><p class='title'>Tracking-Modus</p><p class='value'>{html.escape(str(state['tracking_mode'] or '-'))}</p></div>"
        + f"<div class='card kpi'><p class='title'>Aktives Intervall</p><p class='value mono'>{html.escape(str(state['active_interval'] or '-'))} s</p></div>"
        + f"<div class='card kpi'><p class='title'>Letzte Bewegungsdistanz</p><p class='value mono'>{html.escape(str(state['movement_distance_m'] or '-'))} m</p></div>"
        + f"<div class='card kpi'><p class='title'>Letzte Sender-Accuracy</p><p class='value mono'>{html.escape(str(state['last_accuracy'] or '-'))}</p></div>"
        + f"<div class='card kpi'><p class='title'>CPU Temperatur</p><p class='value mono'>{html.escape(str(health['cpu_temp_c']))}</p></div>"
        + f"<div class='card kpi'><p class='title'>Load (1/5/15)</p><p class='value mono'>{html.escape(str(health['load']))}</p></div>"
        + f"<div class='card kpi'><p class='title'>RAM</p><p class='value mono'>{html.escape(str(health['ram']))}</p></div>"
        + f"<div class='card kpi'><p class='title'>Uptime</p><p class='value mono'>{html.escape(str(health['uptime']))}</p></div>"
        + "</div>"
        + "</div>"
    )
    return html_page(body, title="Status", refresh_seconds=5)
# --- /Smart Van: Status Endpoint ---


@app.route("/wg")
def wg_page():
    vpn = _vpn_status()
    wg_show = ""
    if vpn.get("active"):
        try:
            wg_show = subprocess.run(["wg", "show", "wg0"], capture_output=True, text=True).stdout.strip()
        except Exception as e:
            wg_show = f"wg show Fehler: {e}"

    cfg = load_wg_struct()
    raw = load_wg_raw()
    resolved_ip = wg_resolve_endpoint_ip(cfg.get("endpoint", ""))
    endpoint_host = wg_endpoint_host(cfg.get("endpoint", ""))
    transfer = wg_transfer()

    notice = ""
    saved = request.args.get("saved", "").strip()
    if saved == "raw":
        notice = "<div class='notice ok'>WireGuard-Konfiguration gespeichert.</div>"
    elif saved == "struct":
        notice = "<div class='notice ok'>WireGuard-Formular gespeichert.</div>"
    elif saved == "keys":
        notice = "<div class='notice ok'>Neues Keypair erzeugt. Noch nicht gespeichert.</div>"
    elif saved == "ctl":
        notice = "<div class='notice ok'>VPN-Aktion ausgeführt.</div>"

    body = (
        nav("wg")
        + "<div class='card'>"
        + "<div class='header'>"
        + "<h1 class='h1'>WireGuard VPN</h1>"
        + "<span class='badge'>wg0</span>"
        + "</div>"
        + notice
        + "<div class='grid'>"
        + f"<div class='card kpi'><p class='title'>Status</p><p class='value mono'>{html.escape(str(vpn.get('state', '-')))}</p></div>"
        + f"<div class='card kpi'><p class='title'>Config-Datei</p><p class='value mono'>{html.escape(WG_CONF)}</p></div>"
        + f"<div class='card kpi'><p class='title'>Endpoint Host</p><p class='value mono'>{html.escape(endpoint_host or '-')}</p></div>"
        + f"<div class='card kpi'><p class='title'>Resolved IP</p><p class='value mono'>{html.escape(resolved_ip)}</p></div>"
        + f"<div class='card kpi'><p class='title'>Empfangen (Rx)</p><p class='value mono'>{html.escape(str(transfer.get('rx', '-')))} B</p></div>"
        + f"<div class='card kpi'><p class='title'>Gesendet (Tx)</p><p class='value mono'>{html.escape(str(transfer.get('tx', '-')))} B</p></div>"
        + "</div>"
        + "<div class='hr'></div>"

        + "<div class='header'>"
        + "<h1 class='h1'>Raw Config</h1>"
        + "<span class='badge'>Paste wie Desktop-App</span>"
        + "</div>"
        + "<form method='post' action='/wg/save-raw'>"
        + "<textarea name='raw_config' style='width:100%;min-height:320px;padding:12px;border-radius:12px;border:1px solid #263244;background:#0b1220;color:#e6edf3;outline:none;font-family:ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, Liberation Mono, monospace;'>"
        + html.escape(raw)
        + "</textarea>"
        + "<div style='margin-top:12px'><button class='btn' type='submit'>Raw Config speichern</button></div>"
        + "</form>"

        + "<div class='hr'></div>"

        + "<div class='header'>"
        + "<h1 class='h1'>Wizard / Formular</h1>"
        + "<span class='badge'>Client-Konfiguration</span>"
        + "</div>"
        + "<form method='post' action='/wg/generate-keys'>"
        + "<div style='margin-top:8px'><button class='btn' type='submit'>Generate Keys</button></div>"
        + "</form>"

        + "<form method='post' action='/wg/save-struct'>"
        + "<label>PrivateKey</label>"
        + f"<input type='text' name='private_key' value='{html.escape(cfg.get('private_key',''))}' placeholder='Client PrivateKey'>"

        + "<label>Address</label>"
        + f"<input type='text' name='address' value='{html.escape(cfg.get('address',''))}' placeholder='10.0.0.2/24'>"

        + "<label>DNS</label>"
        + f"<input type='text' name='dns' value='{html.escape(cfg.get('dns',''))}' placeholder='10.0.0.1'>"

        + "<label>Server PublicKey</label>"
        + f"<input type='text' name='public_key' value='{html.escape(cfg.get('public_key',''))}' placeholder='Server PublicKey'>"

        + "<label>Endpoint</label>"
        + f"<input type='text' name='endpoint' value='{html.escape(cfg.get('endpoint',''))}' placeholder='example.com:51820'>"

        + "<label>AllowedIPs</label>"
        + f"<input type='text' name='allowed_ips' value='{html.escape(cfg.get('allowed_ips',''))}' placeholder='10.0.0.0/24'>"

        + "<label>PersistentKeepalive</label>"
        + f"<input type='number' name='persistent_keepalive' min='0' max='65535' step='1' value='{html.escape(str(cfg.get('persistent_keepalive','')))}' placeholder='25'>"

        + "<div style='margin-top:14px'><button class='btn' type='submit'>Formular speichern</button></div>"
        + "</form>"

        + "<div class='hr'></div>"

        + "<div class='header'>"
        + "<h1 class='h1'>VPN-Steuerung</h1>"
        + "<span class='badge'>systemctl wg-quick@wg0</span>"
        + "</div>"
        + "<form method='post' action='/wg/control' style='display:flex;gap:10px;flex-wrap:wrap'>"
        + "<button class='btn' name='action' value='start'>Start VPN</button>"
        + "<button class='btn' name='action' value='stop'>Stop VPN</button>"
        + "<button class='btn' name='action' value='restart'>Restart VPN</button>"
        + "</form>"

        + "<div class='hr'></div>"

        + "<div class='header'>"
        + "<h1 class='h1'>Aktiver Tunnel</h1>"
        + "<span class='badge'>wg show</span>"
        + "</div>"
        + "<pre class='mono' style='white-space:pre-wrap'>"
        + html.escape(wg_show if wg_show else "wg0 aktuell nicht aktiv oder keine Ausgabe verfügbar.")
        + "</pre>"

        + "</div>"
    )
    return html_page(body, title="WireGuard VPN")


@app.route("/wg/save-raw", methods=["POST"])
def wg_save_raw():
    raw = request.form.get("raw_config", "")
    if "[Interface]" not in raw or "[Peer]" not in raw:
        body = nav("wg") + "<div class='card'><div class='notice err'>Ungültige Config: [Interface] und [Peer] erforderlich.</div><a class='btn' href='/wg'>Zurück</a></div>"
        return html_page(body, title="WireGuard Fehler"), 400
    save_wg_raw(raw)
    return redirect("/wg?saved=raw")


@app.route("/wg/save-struct", methods=["POST"])
def wg_save_struct():
    cfg = {
        "private_key": request.form.get("private_key", "").strip(),
        "address": request.form.get("address", "").strip(),
        "dns": request.form.get("dns", "").strip(),
        "public_key": request.form.get("public_key", "").strip(),
        "endpoint": request.form.get("endpoint", "").strip(),
        "allowed_ips": request.form.get("allowed_ips", "").strip(),
        "persistent_keepalive": request.form.get("persistent_keepalive", "").strip(),
    }

    err = []
    if not cfg["private_key"]:
        err.append("PrivateKey fehlt")
    if not cfg["address"]:
        err.append("Address fehlt")
    if not cfg["public_key"]:
        err.append("Server PublicKey fehlt")
    if not cfg["endpoint"]:
        err.append("Endpoint fehlt")
    if not cfg["allowed_ips"]:
        err.append("AllowedIPs fehlt")

    if cfg["persistent_keepalive"]:
        try:
            pka = int(cfg["persistent_keepalive"])
            if pka < 0 or pka > 65535:
                err.append("PersistentKeepalive muss 0..65535 sein")
        except Exception:
            err.append("PersistentKeepalive ist ungültig")

    if err:
        body = nav("wg") + "<div class='card'><div class='notice err'>" + "<br>".join(map(html.escape, err)) + "</div><a class='btn' href='/wg'>Zurück</a></div>"
        return html_page(body, title="WireGuard Fehler"), 400

    save_wg_struct(cfg)
    return redirect("/wg?saved=struct")


@app.route("/wg/generate-keys", methods=["POST"])
def wg_generate_keys_route():
    kp = wg_generate_keypair()
    cfg = load_wg_struct()
    cfg["private_key"] = kp["private"]
    save_wg_struct(cfg)
    return redirect("/wg?saved=keys")


@app.route("/wg/control", methods=["POST"])
def wg_control_route():
    action = request.form.get("action", "").strip().lower()
    if action not in ["start", "stop", "restart"]:
        body = nav("wg") + "<div class='card'><div class='notice err'>Ungültige Aktion.</div><a class='btn' href='/wg'>Zurück</a></div>"
        return html_page(body, title="WireGuard Fehler"), 400
    wg_control(action)
    return redirect("/wg?saved=ctl")


app.secret_key = load_or_create_secret_key()
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=SESSION_TIMEOUT_MINUTES)
init_auth_defaults()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
