#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/Lupus1988/smart-traccar-panel.git"
TMP_DIR="/tmp/smart-traccar-install"

echo "======================================"
echo "Smart Traccar Panel Installer"
echo "======================================"

if [ "${EUID:-$(id -u)}" -ne 0 ]; then
  echo "Please run as root"
  exit 1
fi

echo
echo "Installing base packages..."
apt update
apt install -y \
  git \
  gpsd \
  python3-gps \
  python3-requests \
  python3-flask \
  network-manager \
  wireguard-tools

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "$SCRIPT_DIR/panel/app.py" ] && \
   [ -f "$SCRIPT_DIR/traccar/sender.py" ] && \
   [ -f "$SCRIPT_DIR/traccar/send_test.py" ] && \
   [ -f "$SCRIPT_DIR/traccar/config.json.example" ] && \
   [ -f "$SCRIPT_DIR/systemd/van-panel.service" ] && \
   [ -f "$SCRIPT_DIR/systemd/van-traccar-sender.service" ] && \
   [ -f "$SCRIPT_DIR/networkmanager/van-hotspot.nmconnection" ]; then
  echo
  echo "Using local project files from: $SCRIPT_DIR"
  SRC_DIR="$SCRIPT_DIR"
else
  echo
  echo "Downloading project from GitHub..."
  rm -rf "$TMP_DIR"
  git clone "$REPO_URL" "$TMP_DIR"
  SRC_DIR="$TMP_DIR"
fi

cd "$SRC_DIR"

echo
echo "Creating directories..."
install -d -m 755 /opt/van-panel /opt/van-traccar

echo
echo "Installing panel..."
install -m 644 panel/app.py /opt/van-panel/app.py

echo
echo "Installing traccar client..."
install -m 755 traccar/sender.py /opt/van-traccar/sender.py
install -m 644 traccar/send_test.py /opt/van-traccar/send_test.py

if [ ! -f /opt/van-traccar/config.json ]; then
  install -m 644 traccar/config.json.example /opt/van-traccar/config.json
fi

echo
echo "Ensuring runtime files exist..."
[ -f /opt/van-traccar/status.json ] || printf '{}\n' > /opt/van-traccar/status.json
[ -f /opt/van-traccar/queue.json ] || printf '[]\n' > /opt/van-traccar/queue.json
chmod 644 /opt/van-traccar/status.json /opt/van-traccar/queue.json

echo
echo "Installing systemd services..."
install -m 644 systemd/van-panel.service /etc/systemd/system/van-panel.service
install -m 644 systemd/van-traccar-sender.service /etc/systemd/system/van-traccar-sender.service
install -m 755 systemd/van-wifi-autofallback.sh /usr/local/sbin/van-wifi-autofallback.sh
install -m 644 systemd/van-wifi-autofallback.service /etc/systemd/system/van-wifi-autofallback.service
install -m 644 systemd/van-wifi-autofallback.timer /etc/systemd/system/van-wifi-autofallback.timer

systemctl daemon-reload
systemctl enable van-panel.service van-traccar-sender.service van-wifi-autofallback.timer

echo
echo "Installing hotspot profile..."
nmcli connection delete van-hotspot >/dev/null 2>&1 || true
rm -f /etc/NetworkManager/system-connections/van-hotspot.nmconnection
install -m 600 networkmanager/van-hotspot.nmconnection /etc/NetworkManager/system-connections/van-hotspot.nmconnection

echo
echo "Restarting NetworkManager..."
systemctl restart NetworkManager

echo
echo "Starting services..."
systemctl restart van-panel.service
systemctl restart van-traccar-sender.service

PANEL_IP="$(hostname -I | awk '{print $1}')"

echo
echo "======================================"
echo "Installation complete"
echo "Webpanel:"
if [ -n "$PANEL_IP" ]; then
  echo "http://$PANEL_IP"
else
  echo "IP not available yet"
fi
echo "======================================"
