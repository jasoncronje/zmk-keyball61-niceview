#!/usr/bin/env python3
"""Replay exact hand movements through a model of the firmware's pointer path.

    python3 tools/pointerbench/sim.py

No keyboard needed, and the same input always gives the same output, so two
firmware designs can be compared without flashing either. The model follows
the code integer for integer:

  sensor   PMW3610 at 250 Hz: whole counts every 4 ms, nothing when still
  accel    modules/pointer-accel (speed from step / time since last step)
  resample the ZMK fork's hog.c even-time-slice resampler and report pacing

What it can't know is when each sensor reading reaches the accel processor.
A USB-log build (2026-11-19) saw readings arrive in clumps: two within 0.2 ms
after a ~9 ms wait. `clump` is the share of readings held back until the next
one; 0 is a perfectly punctual sensor thread.

Scores, each for the same movement repeated with the ball starting at 200
different sub-count positions (lower is better for all three):

  travel spread  how much the pointer's total travel varies between repeats
                 of one identical hand movement, as +-% (2 standard deviations)
  gain range     lowest and highest gain any reading got in a steady move
  step spread    variation in the size of BLE reports at steady speed, +-%
"""
import math
import random
import statistics

ONE = 1000
SENSOR_US = 4000
LINK_US = 7500
IDLE_RESET_US = 100_000
MIN_STEP_US = 1000
COUNTS_PER_MM = 31.5


def isqrt(v):
    return math.isqrt(v)


def factor_for(speed, lo_s, hi_s, lo_f, hi_f):
    if speed <= lo_s:
        return lo_f
    if speed >= hi_s:
        return hi_f
    t = (speed - lo_s) * ONE // (hi_s - lo_s)
    s = t * t * (3 * ONE - 2 * t) // (ONE * ONE)
    return lo_f + (hi_f - lo_f) * s // ONE


def tdiv(a, b):
    """C integer division (truncates toward zero)."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


class Accel:
    """input_processor_pointer_accel.c. timing: 'arrival' as shipped, or
    'period' = readings under three sensor periods apart count as one period."""

    def __init__(self, lo_f=1400, hi_f=2300, lo_s=400, hi_s=1500, smoothing=400, timing="arrival"):
        self.cfg = (lo_s, hi_s, lo_f, hi_f)
        self.smoothing = smoothing
        self.timing = timing
        self.factor = lo_f
        self.speed = 0
        self.last_us = -10**9
        self.rem = [0, 0]
        self.gains = []

    def _apply(self, raw, i):
        total = raw * self.factor + self.rem[i]
        out = tdiv(total, ONE)
        self.rem[i] = total - out * ONE
        return out

    def step(self, now, x, y):
        if now - self.last_us > IDLE_RESET_US:
            self.factor = self.cfg[2]
        self.gains.append(self.factor)
        ox, oy = self._apply(x, 0), self._apply(y, 1)
        dt = now - self.last_us
        self.last_us = now
        if dt > IDLE_RESET_US:
            self.speed = 0
            self.rem = [0, 0]
        else:
            if self.timing == "period" and dt < 3 * SENSOR_US:
                dt = SENSOR_US
            dt = max(dt, MIN_STEP_US)
            inst = isqrt(x * x + y * y) * 1_000_000 // dt
            self.speed = (self.speed * (1000 - self.smoothing) + inst * self.smoothing) // 1000
        self.factor = factor_for(self.speed, *self.cfg)
        return ox, oy


class Flat:
    def __init__(self, f=1400):
        self.f, self.rem, self.gains = f, [0, 0], []

    def step(self, now, x, y):
        out = []
        for i, raw in enumerate((x, y)):
            total = raw * self.f + self.rem[i]
            o = tdiv(total, ONE)
            self.rem[i] = total - o * ONE
            out.append(o)
        self.gains.append(self.f)
        return tuple(out)


class Resampler:
    """hog.c CONFIG_ZMK_BLE_MOUSE_REPORT_RESAMPLE, driven by a list of events."""
    RS_ONE = 256

    def __init__(self):
        self.seg = []  # [start, end, x, y]
        self.last = -10**9
        self.acc = [0, 0]
        self.next_send = 0
        self.reports = []

    def add(self, now, dx, dy):
        if dx == 0 and dy == 0:
            return
        dur = now - self.last
        if self.seg and dur < SENSOR_US // 4:
            self.seg[-1][2] += dx * self.RS_ONE
            self.seg[-1][3] += dy * self.RS_ONE
            return
        if dur <= 0 or dur > 2 * SENSOR_US:
            dur = SENSOR_US
        if len(self.seg) == 8:
            s = self.seg.pop(0)
            self.acc[0] += s[2]
            self.acc[1] += s[3]
        self.seg.append([now - dur, now, dx * self.RS_ONE, dy * self.RS_ONE])
        self.last = now

    def _out(self, i, last):
        a = self.acc[i]
        q = tdiv(a + (self.RS_ONE // 2 if a >= 0 else -self.RS_ONE // 2), self.RS_ONE) if last \
            else tdiv(a, self.RS_ONE)
        self.acc[i] -= q * self.RS_ONE
        if last and -self.RS_ONE < self.acc[i] < self.RS_ONE:
            self.acc[i] = 0
        return q

    def take(self, cutoff):
        while self.seg:
            s = self.seg[0]
            if s[1] <= cutoff:
                self.acc[0] += s[2]
                self.acc[1] += s[3]
                self.seg.pop(0)
                continue
            if s[0] < cutoff:
                span = s[1] - s[0]
                px = tdiv(s[2] * (cutoff - s[0]), span)
                py = tdiv(s[3] * (cutoff - s[0]), span)
                self.acc[0] += px
                self.acc[1] += py
                s[2] -= px
                s[3] -= py
                s[0] = cutoff
            break
        last = not self.seg
        return self._out(0, last), self._out(1, last)

    def pending(self):
        return bool(self.seg) or self.acc != [0, 0]

    def run_until(self, t_end, wake):
        """Run the send work item from time `wake` up to t_end."""
        t = wake
        while t is not None and t <= t_end:
            if not self.pending():
                return None
            if t < self.next_send:
                t = self.next_send
                continue
            x, y = self.take(t - SENSOR_US)
            if x or y:
                self.reports.append((t, x, y))
                self.next_send = t + LINK_US
                t = t + LINK_US if self.pending() else None
            else:
                t = t + 1000 if self.pending() else None
        return t


def simulate(path, duration_us, accel, clump=0.0, seed=0):
    """path(t_us) -> (x, y) ball position in counts. Returns (reports, accel)."""
    rng = random.Random(seed)
    phase = (rng.random(), rng.random())
    readings = []
    prev = (math.floor(phase[0]), math.floor(phase[1]))
    t = SENSOR_US
    while t <= duration_us:
        px, py = path(t)
        cur = (math.floor(px + phase[0]), math.floor(py + phase[1]))
        dx, dy = cur[0] - prev[0], cur[1] - prev[1]
        prev = cur
        if dx or dy:
            readings.append([t + rng.randrange(0, 200), dx, dy])
        t += SENSOR_US
    # Clumps: a held-back reading arrives 0.2 ms after the next one.
    for i in range(len(readings) - 1):
        if rng.random() < clump and readings[i + 1][0] - readings[i][0] < 2 * SENSOR_US:
            readings[i][0], readings[i + 1][0] = readings[i + 1][0], readings[i + 1][0] + 200
    rs = Resampler()
    wake = None
    for now, dx, dy in readings:
        if wake is not None:
            wake = rs.run_until(now, wake)
        ox, oy = accel.step(now, dx, dy)
        rs.add(now, ox, oy)
        wake = rs.run_until(now, now)
    if wake is not None:
        rs.run_until(duration_us + 200_000, wake)
    return rs.reports, accel


def line(speed_mm_s, angle_deg=30):
    v = speed_mm_s * COUNTS_PER_MM / 1e6
    c, s = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))
    return lambda t: (v * t * c, v * t * s)


def spread(values):
    m = statistics.mean(values)
    return 200 * statistics.pstdev(values) / m if m else 0.0


def score(make_accel, speed_mm_s, clump, repeats=200, duration_us=400_000):
    travels, steps, lo, hi = [], [], 10**9, 0
    for seed in range(repeats):
        reports, accel = simulate(line(speed_mm_s), duration_us, make_accel(), clump, seed)
        travels.append(math.hypot(sum(r[1] for r in reports), sum(r[2] for r in reports)))
        body = reports[3:-3]
        steps += [math.hypot(r[1], r[2]) for r in body]
        steady = accel.gains[5:]
        lo, hi = min(lo, min(steady)), max(hi, max(steady))
    return spread(travels), lo / ONE, hi / ONE, spread(steps)


DESIGNS = [
    ("shipped: speed from arrival time", lambda: Accel()),
    ("speed from sensor period (8cee5b7)", lambda: Accel(timing="period")),
    ("sensor period + slower average", lambda: Accel(timing="period", smoothing=150)),
    ("flat 1.4x, no acceleration", lambda: Flat(1400)),
]


def main():
    for clump in (0.0, 0.3):
        print(f"\nSensor readings held back and arriving in a clump: {clump:.0%}")
        print(f"  {'design':<38}{'ball speed':>11}{'travel spread':>15}{'gain range':>14}{'step spread':>13}")
        for name, make in DESIGNS:
            for speed in (8, 15, 25, 40, 80):
                t, lo, hi, s = score(make, speed, clump)
                print(f"  {name:<38}{speed:>8} mm/s{t:>13.1f}%{lo:>8.2f}-{hi:.2f}{s:>12.0f}%")


if __name__ == "__main__":
    main()
