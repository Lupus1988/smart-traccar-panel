# Smart Traccar Panel

GPS Tracking Client für Raspberry Pi Fahrzeuge.

## Features

- GPS über gpsd
- Traccar Versand
- Lokales Webpanel
- WLAN / Hotspot / WG-VPN

## Hardware

Empfohlen:

Raspberry Pi Zero 2 W  
USB GPS Modul (u-blox)

## Standardpfade

### Webpanel
/opt/van-panel/app.py

### Traccar Client
/opt/van-traccar/config.json  
/opt/van-traccar/status.json  
/opt/van-traccar/queue.json  
/opt/van-traccar/sender.py  
/opt/van-traccar/send_test.py

### systemd
/etc/systemd/system/van-panel.service  
/etc/systemd/system/van-traccar-sender.service

### NetworkManager
/etc/NetworkManager/system-connections/van-hotspot.nmconnection

## Webpanel

Standardzugriff nach Installation:
http://<pi-ip>

Navigation:
- WLAN-Einrichtung
- Hotspot
- Status
- Traccar Client
- WG-VPN

## Default-Hotspot

SSID: traccar-hotspot  
Sicherheit: offen  
Panel bei Hotspot typischerweise: http://10.42.0.1

## Installation

### Lokales Release

tar -xzf smart-traccar-panel-release.tar.gz
cd smart-traccar-test
sudo ./install.sh

### GitHub Installation (nach Veröffentlichung)

curl -sSL https://raw.githubusercontent.com/<USER>/smart-traccar-panel/main/install.sh | sudo bash


## Abhängigkeiten

Der Installer installiert automatisch:

- git
- gpsd
- python3-gps
- python3-requests
- python3-flask
- network-manager
- wireguard-tools

## Services

Panel:

sudo systemctl status van-panel.service

Sender:

sudo systemctl status van-traccar-sender.service

## Version

Smart Traccar Panel v1.0  
by Norman Knittel

