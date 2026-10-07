#!/usr/bin/env python3
"""Dante network watchdog. Must run as root (PTP ports 319/320 are privileged).

Logs to log/YYYY-MM-DD.log next to this file:
  CLOCK  PTP master identity, master changes, sync gaps > GAP_S
  PING   a Dante device stops answering / comes back
  LINK   the capture interface goes down / up
  INFO   start-up facts

Devices to ping come from devices.txt (name=ip, optional seed) plus continuous
discovery: every Dante device seen via mDNS or in the ARP table is added and
logged as NEW. Power a device on later and it is picked up within a minute.
"""
import os, re, socket, struct, subprocess, sys, time, datetime, pathlib

HERE = pathlib.Path(__file__).resolve().parent
LOGDIR = HERE / "log"
GAP_S = 1.0                 # Dante sync is 4/s; >1s without one is a clock event
PING_EVERY = 5
DISCOVER_EVERY = 60         # rescan mDNS + ARP for devices that appear later

def log(level, msg):
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    line = f"{ts} {level:5} {msg}\n"
    LOGDIR.mkdir(parents=True, exist_ok=True)
    with open(LOGDIR / f"{ts[:10]}.log", "a") as f:
        f.write(line)
    sys.stdout.write(line); sys.stdout.flush()

def sh(*cmd, timeout=10):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout

def find_iface(wanted=None):
    """Interface to watch: --iface if given, else the first non-Wi-Fi port holding a 169.254.x address."""
    if wanted:
        return wanted
    for i in sh("ifconfig", "-l").split():
        if i in ("lo0", "en0") or not i.startswith("en"):
            continue
        if re.search(r"inet 169\.254\.", sh("ifconfig", i)):
            return i
    return None

def iface_ip(iface):
    return sh("ipconfig", "getifaddr", iface).strip() or None

def link_status(iface):
    out = sh("ifconfig", iface)
    st = "active" if "status: active" in out else "inactive"
    media = next((l.strip() for l in out.splitlines() if "media:" in l), "")
    return st, media

def load_devices():
    f = HERE / "devices.txt"
    devs = {}
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if "=" in line:
                k, v = line.split("=", 1); devs[k.strip()] = v.strip()
        return devs
    return devs

def arp_hosts(iface):
    """Every host the switch has let us see: {ip: mac}."""
    out = sh("arp", "-an", "-i", iface)
    return {m.group(1): m.group(2) for m in re.finditer(r"\((169\.254\.[\d.]+)\) at ([0-9a-f:]+) on", out)}

def mdns_hosts():
    p = subprocess.Popen(["dns-sd", "-B", "_netaudio-arc._udp", "local."], stdout=subprocess.PIPE, text=True)
    time.sleep(4); p.terminate()
    names = {l.split()[-1] for l in p.stdout.read().splitlines() if " Add " in l}
    devs = {}
    for n in sorted(names):
        m = re.search(r"ip_address: (\S+)", sh("dscacheutil", "-q", "host", "-a", "name", f"{n}.local"))
        if m: devs[n] = m.group(1)
    return devs

def ptp_socket(local_ip):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    s.bind(("", 319))
    mreq = struct.pack("4s4s", socket.inet_aton("224.0.1.129"), socket.inet_aton(local_ip))
    s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    s.settimeout(0.5)
    return s

def main():
    if os.geteuid() != 0:
        print("run with sudo (PTP port 319 is privileged)"); sys.exit(2)
    wanted = sys.argv[sys.argv.index("--iface") + 1] if "--iface" in sys.argv else None
    iface = find_iface(wanted)
    if not iface:
        log("ERROR", "no Ethernet interface with a 169.254.x address. Is the cable in and the port set to DHCP?"); sys.exit(1)
    ip = iface_ip(iface)
    st, media = link_status(iface)
    log("INFO", f"start on {iface} {ip} link={st} {media}")
    devices = load_devices()          # seed from devices.txt (optional)
    known_ips = set(devices.values())
    def discover(first=False):
        found = mdns_hosts()
        for ip, mac in arp_hosts(iface).items():
            if ip != ip_self and ip not in found.values():
                found[f"host-{mac}"] = ip
        for name, ip in found.items():
            if not ip.startswith("169.254."):
                continue                      # Wi-Fi/office-LAN hosts are not on the Dante segment
            if ip not in known_ips:
                known_ips.add(ip); devices[name] = ip
                log("INFO" if first else "NEW", f"device {name} {ip}")
    ip_self = ip
    discover(first=True)
    log("INFO", f"watching {len(devices)} devices")
    last_discover = time.time()
    today = datetime.date.today()
    sock = ptp_socket(ip)
    master = None
    master_src = None
    last_sync = time.time()
    gap_open = False
    last_ping = 0
    last_link = st
    down = set()
    while True:
        # --- PTP (v1): control byte at offset 32, 0 = Sync; sourceUuid at 22..27
        try:
            data, (src, _) = sock.recvfrom(2048)
            if len(data) > 32 and data[32] == 0:
                uuid = data[22:28].hex(":")
                now = time.time()
                if uuid != master:
                    log("CLOCK", f"PTP master now {src} ({uuid})" + (f", was {master}" if master else ""))
                    master, master_src = uuid, src
                if gap_open:
                    log("CLOCK", f"sync resumed after {now-last_sync:.1f}s")
                    gap_open = False
                last_sync = now
        except socket.timeout:
            pass
        now = time.time()
        if not gap_open and now - last_sync > GAP_S:
            log("CLOCK", f"no PTP sync for {now-last_sync:.1f}s (master {master})")
            gap_open = True
        if datetime.date.today() != today:        # new day's log file: restate state so it stands alone
            today = datetime.date.today()
            log("INFO", f"start on {iface} {ip} link={last_link} (day rollover)")
            for name, addr in devices.items():
                log("INFO", f"device {name} {addr}")
            if master:
                log("CLOCK", f"PTP master now {master_src} ({master})")
        if now - last_discover >= DISCOVER_EVERY:
            last_discover = now; discover()
        # --- link + ping
        if now - last_ping >= PING_EVERY:
            last_ping = now
            st, media = link_status(iface)
            if st != last_link:
                log("LINK", f"{iface} {last_link} -> {st} {media}")
                last_link = st
            for name, addr in devices.items():
                r = sh("ping", "-c", "1", "-W", "800", "-b", iface, addr)
                ok = " 0.0% packet loss" in r
                if not ok and name not in down:
                    log("PING", f"{name} {addr} unreachable"); down.add(name)
                elif ok and name in down:
                    log("PING", f"{name} {addr} back"); down.discard(name)

if __name__ == "__main__":
    main()
