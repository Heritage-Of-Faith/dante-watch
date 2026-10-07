# dante-watch

Watchdog for the Dante audio network. Runs on a Mac plugged into the Dante switch
during a service and writes a timestamped log of clock events, device loss and link
flaps. Purpose: the next time audio drops, we have evidence of *what* dropped.

Nothing here changes any device or switch. It only listens and pings.

## Sunday runbook

Needs: a Mac with a USB Ethernet adapter, admin password for that Mac, Python 3
(ships with macOS). No other installs.

1. Plug the Mac into a free port on the **Netgear M4100** (the Dante switch).
2. System Settings → Network → the USB LAN adapter → Configure IPv4: **Using DHCP**.
   After ~10 s it self-assigns a 169.254.x.x address. That is correct — the Dante
   network has no DHCP server.
3. Open Terminal, then:
   ```
   cd ~/dante-watch
   ./start.sh
   ```
   Enter the Mac password when asked. It prints `running.`
4. Leave the Mac on, lid open, plugged into power, for the whole service.
5. If audio drops, **note the clock time** on paper. That's what we match against the log.
6. After the service: `./report.sh` prints the day's summary. Send that output (or the
   file `log/YYYY-MM-DD.log`) to Matt.
7. `./stop.sh` when done. `./status.sh` any time to check it is still running.

## Live UI

`./ui.sh` starts a small web page (no sudo, no installs) and opens http://localhost:8787.
It shows RUNNING / NOT RUNNING, the current PTP master, a tile per device (green up,
red down), and the day's events as they happen, newest at top. The page flashes on any
CLOCK / PING / LINK line. To watch from a phone, use the second URL `ui.sh` prints —
that only works if the Mac's Wi-Fi is on and the phone is on the same Wi-Fi. The Dante
LAN itself has no Wi-Fi and no internet; the page needs neither.

## What the log lines mean

| Line | Meaning | Points at |
|---|---|---|
| `CLOCK PTP master now …, was …` | The clock leader changed | Clocking config (Preferred Leader), a device rebooting, or a switch issue |
| `CLOCK no PTP sync for N s` | No clock messages reached this Mac | Switch dropped multicast, switch reboot, EEE/link issue |
| `PING <device> unreachable` | A device stopped answering | That device or its cable/port |
| `LINK en7 active -> inactive` | This Mac's own cable/port went down | The port this Mac is on, or the switch |
| nothing at the drop time | Network was fine from this port | Problem is on another switch port/segment, or not network — look at the console |

The DM7C console is the clock leader today (`ac:44:f2:c9:9a:c2`). Any `master now`
line after start-up is an event worth reading.

## Files

- `dante-watch.py` — the watchdog. `sudo python3 dante-watch.py [--iface en7]`
- `devices.txt` — seed list of devices to ping. Everything else seen on the wire (mDNS or ARP) is auto-added and logged as `NEW`.
- `start.sh` / `stop.sh` / `status.sh` / `report.sh`
- `log/` — one file per day. Not committed.
- `FINDINGS.md` — what we know about the network so far, and what is still open.

## Known limits

- Watches from one switch port. A fault on a different port that doesn't affect
  multicast/PTP to this port shows up only as a `PING` line, or not at all.
- Sync gap threshold is 1 s. Dante devices tolerate short gaps; a logged gap is a
  symptom, not proof of an audible drop. Match it to the noted time.
- PTP parsing is Dante's PTPv1 only (verified against a capture 2026-10-07).
