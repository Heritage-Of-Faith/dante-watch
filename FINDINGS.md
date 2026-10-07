# Dante network — findings log

Append-only. Newest entry at the bottom. Facts here were observed from a Mac on
Netgear port 0/3 unless stated.

## 2026-10-07 — first survey (Matt + Claude)

Context: occasional Dante drops; one on the weekend of 3–4 Oct 2026.

### Topology seen on the wire

| Device | Role | IP | MAC |
|---|---|---|---|
| Yamaha DM7C | console, **PTP clock leader** | 169.254.157.163 | ac:44:f2:c9:9a:c2 |
| Yamaha Rio3224-D "Y001" | stage box | 169.254.200.155 | 00:1d:c1:06:25:ba (Dante) / 00:a0:de:a7:11:06 (Yamaha ctrl, 169.254.195.236) |
| Yamaha Rio3224-D "Y002" | stage box | 169.254.102.101 | 00:1d:c1:0b:b7:84 (Dante) / 00:a0:de:8c:68:32 (Yamaha ctrl, 169.254.36.125) |
| Reaperpc | DAW | 169.254.209.236 | 00:d8:61:ff:cf:36 |
| Admins-MacBook-Pro | DVS / Dante Controller | 169.254.73.20 | f0:18:98:ef:9f:d5 |
| **Netgear M4100-D12G** | switch, fw B1.0.1.0, RSTP root | 10.0.1.28 (LLDP) — also DHCP-requesting | dc:ef:09:d0:cc:dc |
| **TP-Link TL-SG2210MP** v1 | switch, fw 1.0.0 (2020-06), Omada-adopted, **IGMP querier**, uptime 8d (booted ~29 Sep) | 169.254.1.1 | 00:31:92:3b:d8:79 |
| **Cisco SG-series (model unread)** | switch, GoAhead web UI | 169.254.1.2 | 68:ca:e4:f7:7b:dc |

Whole segment is link-local 169.254/16, no DHCP server. Three switches, all managed.
Matt: more devices exist than listed here — not all were on/visible on 7 Oct.

### Captures (sudo tcpdump on en7)

- `en7.pcap`, 2000 pkts in 0.13 s: 100% Dante multicast audio (5 flows, 239.255.x.x:4321, from both Rios) flooded to a port that subscribes to nothing → IGMP snooping is not filtering on the Netgear. ~36 Mbps per port of unsolicited multicast.
- `en7-ctl.pcap`, 74 s, audio filtered: DM7C sole PTP master, sync 4/s, no master change, no gaps. Reaperpc ARPs for a stale gateway 192.168.0.1 every second. DM7C and Rio Y002 send DHCP discovers continuously (normal with no server).

### Config problems found

1. This Mac's USB LAN was static 192.168.10.180/16 — wrong subnet. Set to DHCP 7 Oct (→ 169.254.208.55).
2. Multicast flooding (above). Harmless at gigabit; harmful to any 100 Mbps device or AP on the segment.
3. Netgear firmware B1.0.1.0 is ~2013-era. Early M4100 builds had IGMP/multicast bugs (unverified).
4. EEE status on all three switches: **unread**. Audinate requires EEE off. Defaults on these models are probably off (unverified).

### Not the cause

- LED-MAC-MINI and Reyhans-Mac-mini advertise Dante on the office Wi-Fi LAN (192.168.8.x) only. They are not on the Dante switches.

### Open

- TP-Link login: not held by Matt; it is Omada-adopted — ask whoever adopted it.
- Netgear login + reach (needs `sudo ifconfig en7 alias 10.0.1.250 255.255.255.0`).
- Cisco switch model and login.
- Dante Controller on this Mac is bound to Wi-Fi; needs Primary = USB LAN to read Clock Status / Events.
- What the weekend drop looked like (all devices vs one; duration; self-recovered?).

### Decision

Instrument before fixing: run `dante-watch` during services until a drop is caught in the log, then act on what it shows.
