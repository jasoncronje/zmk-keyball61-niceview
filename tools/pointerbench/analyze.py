#!/usr/bin/env python3
"""Score a ptrec capture: how evenly did each pointing device's reports arrive?

    python3 tools/pointerbench/analyze.py capture.csv [more.csv ...]

Only reports inside a movement are scored (a gap over 100 ms ends a movement),
so pauses of the hand don't count as stutter. For each device:

  rate      median time between reports while moving
  half rate share of quarter-second stretches where most reports came bunched
            or a slot late: the link was delivering every other slot
  on time   share of gaps within 35% of that median: the smooth ones
  bunched   share under 2 ms: two reports delivered together, the pointer
            jumps twice in one screen frame and then stands still
  late      share over 1.5x the median: the pointer stood still for a frame
  uneven    median change in step size from one report to the next, as a share
            of the step (0% = perfectly steady speed), over steady stretches
  clipped   reports with an axis at the 8-bit limit (+-127): movement was lost
  1-count   share of reports that moved a single count: how much of the time
            the device works at its finest step
"""
import csv
import statistics
import struct
import sys
from collections import defaultdict

MOVE_GAP_US = 100_000


def xy_from_report(name, data):
    """X, Y from raw report bytes, for the devices whose layout we know."""
    if name.startswith("Karabiner"):
        # buttons (4 bytes), x, y, wheel, hwheel as int8
        return struct.unpack_from("bb", data, 4)
    if name.startswith("Keyball"):
        # ZMK mouse report: id 3, buttons, x, y as int16 LE
        if data[0] != 3 or len(data) < 6:
            return None
        return struct.unpack_from("<hh", data, 2)
    if name.startswith("MX Ergo"):
        # id 2, buttons (2 bytes), then x and y packed as 12 bits each
        if data[0] != 2 or len(data) < 6:
            return None
        x = data[3] | ((data[4] & 0x0F) << 8)
        y = (data[4] >> 4) | (data[5] << 4)
        return (x - 4096 if x > 2047 else x, y - 4096 if y > 2047 else y)
    return None


def load(path):
    """{(device, transport): [(t_us, x, y)]}, plus the devices held exclusively."""
    raw = defaultdict(dict)   # device -> {t: (x, y)} from raw reports
    vals = defaultdict(dict)  # device -> {t: [x, y]} from parsed elements
    held = set()
    with open(path, newline="") as f:
        for row in csv.reader(f):
            if len(row) < 7:
                continue
            kind, t, name, transport, a, b, extra = row[:7]
            key = (name, transport)
            if kind == "dev" and a == "0":
                held.add(key)
            elif kind == "hid":
                xy = xy_from_report(name, bytes.fromhex(extra))
                if xy is not None:
                    raw[key][int(t)] = xy
            elif kind == "val" and a in ("48", "49"):
                slot = vals[key].setdefault(int(t), [0, 0])
                slot[0 if a == "48" else 1] = int(b)
    out = {}
    for key in set(raw) | set(vals):
        src = raw[key] if raw[key] else {t: tuple(v) for t, v in vals[key].items()}
        events = sorted((t, x, y) for t, (x, y) in src.items() if x or y)
        if events:
            out[key] = events
    return out, held


def pct(n, d):
    return 100.0 * n / d if d else 0.0


def score(events):
    gaps = []
    steps = []
    for (t0, x0, y0), (t1, x1, y1) in zip(events, events[1:]):
        gap = t1 - t0
        if gap > MOVE_GAP_US:
            continue
        gaps.append(gap)
        m0 = (x0 * x0 + y0 * y0) ** 0.5
        m1 = (x1 * x1 + y1 * y1) ** 0.5
        # Step-to-step change only means something away from the 1-2 count floor.
        if min(m0, m1) >= 6:
            steps.append(abs(m1 - m0) / ((m0 + m1) / 2))
    if len(gaps) < 20:
        return None
    med = statistics.median(gaps)
    # Quarter-second windows where most gaps were off the beat.
    windows = defaultdict(lambda: [0, 0])
    for (t0, _, _), (t1, _, _) in zip(events, events[1:]):
        gap = t1 - t0
        if gap <= MOVE_GAP_US:
            w = windows[(t1 - events[0][0]) // 250_000]
            w[0] += 1
            w[1] += gap < 2000 or gap > 1.5 * med
    busy = [w for w in windows.values() if w[0] >= 8]
    return {
        "half_rate": pct(sum(1 for n, bad in busy if bad * 2 >= n), len(busy)),
        "reports": len(events),
        "rate_ms": med / 1000,
        "on_time": pct(sum(1 for g in gaps if abs(g - med) <= 0.35 * med), len(gaps)),
        "bunched": pct(sum(1 for g in gaps if g < 2000), len(gaps)),
        "late": pct(sum(1 for g in gaps if g > 1.5 * med), len(gaps)),
        "worst_ms": max(gaps) / 1000,
        "uneven": 100 * statistics.median(steps) if steps else float("nan"),
        "clipped": sum(1 for _, x, y in events if abs(x) >= 127 or abs(y) >= 127),
        "one_count": pct(sum(1 for _, x, y in events if max(abs(x), abs(y)) == 1), len(events)),
    }


def main(paths):
    for path in paths:
        devices, held = load(path)
        print(f"\n{path}")
        for key in sorted(held):
            print(f"  {key[0]} [{key[1]}]: held exclusively by another program, not readable")
        print(f"  {'device':<34}{'reports':>8}{'rate':>8}{'half rate':>10}{'on time':>9}{'bunched':>9}"
              f"{'late':>7}{'worst':>8}{'uneven':>8}{'clipped':>9}{'1-count':>9}")
        for key in sorted(devices):
            s = score(devices[key])
            label = f"{key[0][:24]} [{key[1]}]"
            if s is None:
                print(f"  {label:<34}{len(devices[key]):>8}  too little movement to score")
                continue
            print(f"  {label:<34}{s['reports']:>8}{s['rate_ms']:>6.1f}ms{s['half_rate']:>9.0f}%{s['on_time']:>8.0f}%"
                  f"{s['bunched']:>8.0f}%{s['late']:>6.0f}%{s['worst_ms']:>6.0f}ms"
                  f"{s['uneven']:>7.0f}%{s['clipped']:>9}{s['one_count']:>8.0f}%")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
