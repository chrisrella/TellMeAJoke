#!/usr/bin/env python3
"""
Print cron lines for poster.py.
YouTube is included by default.
Usage:
    python3 caption-automation/gen_cron.py              # today only, noon, IG+FB+YT
    python3 caption-automation/gen_cron.py --forever    # every day at noon, permanent
    python3 caption-automation/gen_cron.py --from 10 --to 15
    python3 caption-automation/gen_cron.py --count 2    # 2 posts today
    python3 caption-automation/gen_cron.py --no-youtube # exclude YouTube
"""

import argparse
from datetime import date

PYTHON = "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
DIR    = "/Users/chrisrella/TellMeAJoke"

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from",       dest="start",      type=int, default=12, metavar="HOUR")
    parser.add_argument("--to",         dest="end",        type=int, default=12, metavar="HOUR")
    parser.add_argument("--count",      dest="count",      type=int, default=None, metavar="N")
    parser.add_argument("--no-youtube", dest="no_youtube", action="store_true",
                        help="Exclude YouTube from the cron schedule")
    parser.add_argument("--forever",    dest="forever",    action="store_true",
                        help="Output a permanent daily cron (runs every day, not just today)")
    args = parser.parse_args()

    today  = date.today()
    d, m   = (("*", "*") if args.forever else (today.day, today.month))

    end       = args.start + args.count - 1 if args.count else args.end
    yt_flag   = " --no-youtube" if args.no_youtube else ""
    platforms = "IG+FB only" if args.no_youtube else "IG+FB+YT"
    label     = f"{platforms} — every day" if args.forever else platforms

    print(f"\n# {label}")
    for hour in range(args.start, end + 1):
        print(f"0 {hour} {d} {m} * cd {DIR} && {PYTHON} caption-automation/poster.py{yt_flag} >> output/cron.log 2>&1")
    print()

if __name__ == "__main__":
    main()
