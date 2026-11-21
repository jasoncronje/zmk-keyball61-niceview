#!/usr/bin/env python3
"""Guided pointer benchmark: the trackball against a reference mouse.

    python3 tools/pointerbench/bench.py

Records three short takes and prints one score table (see analyze.py for what
the columns mean):

  1. the Keyball as it is set up now
  2. the reference mouse
  3. the Keyball with Karabiner-Elements told to leave it alone, if Karabiner
     is grabbing it. Karabiner's settings are put back afterwards, also on
     Ctrl-C.

    python3 tools/pointerbench/bench.py radio

records the Keyball three times with different neighbours on the air (reference
mouse off, mouse awake, left half off), to find which link costs it report
slots.

In every take do the same thing: slow small circles for the first half, then
quick flicks left and right. Captures are kept in tools/pointerbench/captures/.
"""
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CAPTURES = os.path.join(HERE, "captures")
PTREC = os.path.join(CAPTURES, "ptrec")
KARABINER = os.path.expanduser("~/.config/karabiner/karabiner.json")
KEYBALL = {"vendor_id": 0x1D50, "product_id": 0x615E}
SECONDS = 20

sys.path.insert(0, HERE)
import analyze  # noqa: E402


def build():
    src = os.path.join(HERE, "ptrec.swift")
    if os.path.exists(PTREC) and os.path.getmtime(PTREC) >= os.path.getmtime(src):
        return
    print("Building the recorder (once, about 20 s)...")
    subprocess.run(["swiftc", "-O", "-o", PTREC, src], check=True)


def take(name, prompt):
    path = os.path.join(CAPTURES, f"{name}.csv")
    input(f"\n>>> {prompt}\n    Press Return, then move for {SECONDS} s: "
          "slow small circles first, then quick flicks.")
    with open(path, "w") as out:
        proc = subprocess.Popen([PTREC, str(SECONDS)], stdout=out, stderr=subprocess.DEVNULL)
        for left in range(SECONDS, 0, -1):
            hint = "small circles" if left > SECONDS // 2 else "quick flicks "
            print(f"\r    {hint}  {left:2d} s ", end="", flush=True)
            time.sleep(1)
        proc.wait()
    print("\r    done.                    ")
    return path


def karabiner_keyball_entries(config):
    """The Keyball's device entries in the selected Karabiner profile."""
    found = []
    for profile in config.get("profiles", []):
        if not profile.get("selected"):
            continue
        for dev in profile.get("devices", []):
            ident = dev.get("identifiers", {})
            if all(ident.get(k) == v for k, v in KEYBALL.items()) and not dev.get("ignore"):
                found.append(dev)
    return found


class KarabinerReleased:
    """Tells Karabiner-Elements to leave the Keyball alone, so its raw reports
    can be read. Puts Karabiner's settings back on exit, also on Ctrl-C."""

    def __enter__(self):
        self.backup = None
        if not os.path.exists(KARABINER):
            return self
        with open(KARABINER) as f:
            config = json.load(f)
        entries = karabiner_keyball_entries(config)
        if not entries:
            return self
        self.backup = KARABINER + ".pointerbench-backup"
        shutil.copy2(KARABINER, self.backup)
        for dev in entries:
            dev["ignore"] = True
        with open(KARABINER, "w") as f:
            json.dump(config, f, indent=4)
        print("\nKarabiner is letting go of the Keyball...")
        time.sleep(5)
        return self

    def __exit__(self, *exc):
        if self.backup:
            shutil.copy2(self.backup, KARABINER)
            os.remove(self.backup)
            print("Karabiner's settings are back as they were.")


def compare():
    paths = [take("1-keyball-as-is", "Take 1 of 3: the KEYBALL trackball."),
             take("2-reference-mouse", "Take 2 of 3: the other MOUSE (MX Ergo).")]
    with KarabinerReleased() as released:
        if released.backup:
            paths.append(take("3-keyball-without-karabiner",
                              "Take 3 of 3: the KEYBALL trackball again."))
        else:
            print("\nKarabiner isn't grabbing the Keyball: no third take needed.")
    return paths


def radio():
    """Which other radio link halves the Keyball's report rate? Every take
    records the Keyball; only what else is on the air changes."""
    with KarabinerReleased():
        return [
            take("radio-1-mouse-off",
                 "Take 1 of 3: switch the MX Ergo OFF (switch underneath). Then the KEYBALL."),
            take("radio-2-mouse-awake",
                 "Take 2 of 3: switch the MX Ergo ON and roll its ball for 3 s. Then the KEYBALL."),
            take("radio-3-left-half-off",
                 "Take 3 of 3: MX Ergo OFF again, and the Keyball's LEFT half OFF. Then the KEYBALL."),
        ]


def main():
    os.makedirs(CAPTURES, exist_ok=True)
    build()
    paths = radio() if sys.argv[1:] == ["radio"] else compare()
    analyze.main(paths)
    if sys.argv[1:] == ["radio"]:
        print("\nSwitch the left half and the MX Ergo back on.")


if __name__ == "__main__":
    main()
