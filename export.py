#!/usr/bin/env python3
"""Bundle everything Claude needs to diagnose a Dante drop into one Markdown file.

    python3 export.py [YYYY-MM-DD ...]     default: today

Writes exports/dante-export-<date>-<HHMM>.md and prints the path. Paste the file
into Claude (or attach it) with the operator notes filled in. No root needed.
Contents: a ready-made prompt, operator notes to fill in, network snapshot at
export time, FINDINGS.md, devices.txt, a per-day summary, and the full log(s).
"""
import datetime, pathlib, re, subprocess, sys, collections

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "exports"

def sh(*cmd, timeout=15):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception as e:
        return f"(failed: {e})"

def read(p):
    p = HERE / p
    return p.read_text() if p.exists() else f"(no {p.name})"

def summarise(lines):
    counts = collections.Counter()
    events = []
    for l in lines:
        m = re.match(r"(\S+) (\w+)\s+(.*)", l)
        if not m: continue
        ts, lvl, msg = m.groups()
        counts[lvl] += 1
        if lvl in ("CLOCK", "PING", "LINK", "ERROR", "NEW"):
            events.append(f"- `{ts[11:]}` **{lvl}** {msg}")
    head = ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "empty"
    return head, events

def main():
    days = sys.argv[1:] or [datetime.date.today().isoformat()]
    now = datetime.datetime.now()
    sha = sh("git", "-C", str(HERE), "rev-parse", "--short", "HEAD")
    iface = next((i for i in sh("ifconfig", "-l").split()
                  if i.startswith("en") and i != "en0" and "169.254." in sh("ifconfig", i)), None)
    parts = [f"""# Dante network export — {now:%Y-%m-%d %H:%M}

## Prompt for Claude

You are diagnosing intermittent audio dropouts on a Dante audio-over-IP network at a church.
Below is everything we have: operator notes about what was heard and when, a snapshot of the
network at export time, our standing findings about the topology and switches, and the
watchdog log(s) from the day(s) in question. The watchdog ran on a Mac plugged into the
Netgear switch and logged PTP clock events, device ping loss, link flaps and newly seen devices.

Please: (1) match each operator-noted drop time to log events within ±2 minutes and say what
the network was doing; (2) say which of clock / switch / cable / device / "not network" the
evidence points at, with confidence; (3) list the single next check or change that would most
reduce uncertainty, and what is still unknown. Be terse and specific. If the log is quiet at a
drop time, say so plainly — that is a finding too.

## Operator notes (fill in before sending)

- Service / event:
- Drop times noticed (clock time, be as exact as you can):
- What was heard (silence, clicks, one channel vs all, how long, self-recovered or needed a reboot):
- Anything changed that day (new device, cable moved, firmware, someone on the network with a laptop):

## Snapshot at export time

- Watchdog version: `{sha}`
- Interface: `{iface}`
- ifconfig:
```
{sh("ifconfig", iface) if iface else "(no Dante interface up)"}
```
- ARP table (hosts the switch has let this Mac see):
```
{sh("arp", "-an", "-i", iface) if iface else "(n/a)"}
```
- Dante devices advertising on mDNS:
```
{dante_mdns()}
```

## Standing findings (FINDINGS.md)

{read("FINDINGS.md")}

## devices.txt

```
{read("devices.txt")}
```
"""]
    for d in days:
        p = HERE / "log" / f"{d}.log"
        lines = p.read_text().splitlines() if p.exists() else []
        head, events = summarise(lines)
        parts.append(f"""## Log {d} — summary

Lines by level: {head}

Notable events ({len(events)}):
{chr(10).join(events) if events else "- none"}

## Log {d} — full

```
{chr(10).join(lines) if lines else "(no log for this day)"}
```
""")
    OUT.mkdir(exist_ok=True)
    out = OUT / f"dante-export-{days[0]}-{now:%H%M}.md"
    out.write_text("\n".join(parts))
    print(out)

def dante_mdns():
    try:
        p = subprocess.Popen(["dns-sd", "-B", "_netaudio-arc._udp", "local."], stdout=subprocess.PIPE, text=True)
        import time; time.sleep(3); p.terminate()
        names = sorted({l.split()[-1] for l in p.stdout.read().splitlines() if " Add " in l})
        rows = []
        for n in names:
            m = re.search(r"ip_address: (\S+)", sh("dscacheutil", "-q", "host", "-a", "name", f"{n}.local"))
            rows.append(f"{n} {m.group(1) if m else '?'}")
        return "\n".join(rows) or "(none)"
    except Exception as e:
        return f"(failed: {e})"

if __name__ == "__main__":
    main()
