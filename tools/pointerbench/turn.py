#!/usr/bin/env python3
"""Does the sensor count the same distance at every speed?

    python3 tools/pointerbench/turn.py

Roll the ball the same distance slowly and then fast, and compare the raw
sensor counts (before any gain) that the firmware saw. A healthy sensor gives
the same count both times: one full turn of the 34 mm ball is about 107 mm,
3360 counts at 31.5 counts/mm. A sensor that loses slow movement counts far
fewer on the slow roll, and the pointer then freezes whenever the ball slows.

Needs the key-logger build of the right half (sensor probe, keylog kind 6) and
keylogd running. Roll straight up or down so all movement is on one axis, and
use a mark on the ball to stop after exactly one turn.
"""
import sqlite3
import time
from pathlib import Path

DB = Path.home() / "Library/Application Support/keyball-keylog/keylog.sqlite"
EXPECTED = 3360


def counts_between(start, end):
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT kb_ms, c FROM events WHERE kind = 6 AND host_time BETWEEN ? AND ?",
        (start, end)).fetchall()
    return sum(dict(rows).values()), len(dict(rows))


def roll(label, how):
    input(f"\n>>> {label}: one full turn straight up, {how}.\n"
          "    Hands off the ball, press Return, then roll.")
    start = time.time()
    input("    Finished the turn? Hands off, press Return.")
    end = time.time()
    # The firmware sends a second's tally when the next second of movement
    # starts, so a nudge is needed to push the last one out.
    input("    Now nudge the ball once (any direction) and press Return.")
    time.sleep(1.5)
    counts, seconds = counts_between(start, end + 0.3)
    print(f"    {counts} counts over {seconds} s of movement ({100 * counts / EXPECTED:.0f}% of a full turn)")
    return counts


def main():
    slow = roll("SLOW", "taking about 10 seconds")
    fast = roll("FAST", "in about 1 second")
    crawl = roll("VERY SLOW", "taking about 30 seconds")
    print(f"\nslow {slow}, fast {fast}, very slow {crawl} counts (a full turn should be about {EXPECTED})")
    if fast and min(slow, crawl) < 0.8 * fast:
        print("The sensor counts less distance when the ball moves slowly: it is losing slow movement.")
    elif fast:
        print("The sensor counts the same distance at every speed.")


if __name__ == "__main__":
    main()
