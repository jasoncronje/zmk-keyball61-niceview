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


def main():
    os.makedirs(CAPTURES, exist_ok=True)
    build()

    paths = [take("1-keyball-as-is", "Take 1 of 3: the KEYBALL trackball."),
             take("2-reference-mouse", "Take 2 of 3: the other MOUSE (MX Ergo).")]

    config = None
    if os.path.exists(KARABINER):
        with open(KARABINER) as f:
            config = json.load(f)
    entries = karabiner_keyball_entries(config) if config else []
    if entries:
        backup = KARABINER + ".pointerbench-backup"
        shutil.copy2(KARABINER, backup)
        try:
            for dev in entries:
                dev["ignore"] = True
            with open(KARABINER, "w") as f:
                json.dump(config, f, indent=4)
            print("\nKarabiner is letting go of the Keyball for take 3...")
            time.sleep(5)
            paths.append(take("3-keyball-without-karabiner",
                              "Take 3 of 3: the KEYBALL trackball again."))
        finally:
            shutil.copy2(backup, KARABINER)
            os.remove(backup)
            print("Karabiner's settings are back as they were.")
    else:
        print("\nKarabiner isn't grabbing the Keyball: no third take needed.")

    analyze.main(paths)


if __name__ == "__main__":
    main()
