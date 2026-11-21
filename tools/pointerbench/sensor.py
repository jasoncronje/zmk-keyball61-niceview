#!/usr/bin/env python3
"""How evenly do the trackball's sensor readings reach the firmware?

    python3 tools/pointerbench/sensor.py [--minutes 10]

Reads the sensor timing records that the key-logger firmware build sends once a
second while the ball moves (modules/keylog, kinds 5 and 6), from the key log
database that keylogd fills. The PMW3610 reads every 4 ms, so on a healthy
keyboard nearly every gap between readings is 3-5 ms. Readings under 1 ms
apart arrived as a clump: one was held up and came in with the next. Both the
pointer acceleration and the report resampler time readings by arrival, so
clumps make gain and report sizes jump (tools/pointerbench/sim.py shows how
much for a given share of clumps).
"""
import argparse
import sqlite3
import time
from pathlib import Path

DB = Path.home() / "Library/Application Support/keyball-keylog/keylog.sqlite"
BUCKETS = ["under 1 ms (clump)", "1-3 ms", "3-5 ms (on time)", "5-7 ms", "7-12 ms", "12-100 ms"]


def load(db, since):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT kind, flags, a, b, c, kb_ms FROM events "
        "WHERE kind IN (5, 6) AND host_time >= ? ORDER BY id", (since,)).fetchall()
    # The same record can arrive over USB and BLE: keep one per keyboard time.
    a_rows = {r[5]: r for r in rows if r[0] == 5}
    b_rows = {r[5]: r for r in rows if r[0] == 6}
    return a_rows, b_rows


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--minutes", type=float, default=10, help="how far back to read")
    args = parser.parse_args()

    a_rows, b_rows = load(DB, time.time() - args.minutes * 60)
    if not a_rows:
        raise SystemExit("No sensor timing records yet. They need the key-logger build of the "
                         "right half with the sensor probe, keylogd running, and ball movement.")

    totals = [0] * 6
    worst_gap = most_counts = counts = 0
    clumpy_seconds = 0
    for ms, (_, f, a, b, c, _) in a_rows.items():
        gaps = [f, a, b, c & 0xFF, c >> 8, 0]
        if ms in b_rows:
            _, f2, a2, b2, c2, _ = b_rows[ms]
            gaps[5] = f2
            worst_gap = max(worst_gap, a2)
            most_counts = max(most_counts, b2)
            counts += c2
        totals = [t + g for t, g in zip(totals, gaps)]
        if sum(gaps) >= 20 and gaps[0] * 10 >= sum(gaps):
            clumpy_seconds += 1

    n = sum(totals)
    print(f"{len(a_rows)} seconds of movement, {n} gaps between readings, {counts} counts moved\n")
    for label, value in zip(BUCKETS, totals):
        share = 100 * value / n if n else 0
        print(f"  {label:<20}{value:>8}{share:>7.1f}%  {'#' * round(share / 2)}")
    print(f"\n  longest gap inside a movement: {worst_gap} ms")
    print(f"  most counts in one reading:    {most_counts}")
    print(f"  seconds with 10% or more of readings in clumps: {clumpy_seconds} of {len(a_rows)}")


if __name__ == "__main__":
    main()
