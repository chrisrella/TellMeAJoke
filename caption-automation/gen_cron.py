#!/usr/bin/env python3
"""
Print today's cron lines for poster.py.
YouTube is skipped by default (channel strike active until Jan 25 2027).
Usage:
    python3 caption-automation/gen_cron.py              # 12pm-4pm, IG+FB only
    python3 caption-automation/gen_cron.py --from 10 --to 15
    python3 caption-automation/gen_cron.py --from 12 --count 3
    python3 caption-automation/gen_cron.py --youtube    # re-enable YouTube
"""

import argparse
from datetime import date

PYTHON = "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
DIR    = "/Users/chrisrella/TellMeAJoke"

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from",    dest="start",   type=int, default=12, metavar="HOUR")
    parser.add_argument("--to",      dest="end",     type=int, default=16, metavar="HOUR")
    parser.add_argument("--count",   dest="count",   type=int, default=None, metavar="N")
    parser.add_argument("--youtube", dest="youtube", action="store_true",
                        help="Include YouTube (off by default — strike active until Jan 25 2027)")
    args = parser.parse_args()

    today = date.today()
    d, m  = today.day, today.month

    end        = args.start + args.count - 1 if args.count else args.end
    yt_flag    = "" if args.youtube else " --no-youtube"
    platforms  = "IG+FB+YT" if args.youtube else "IG+FB only (--youtube to re-enable)"

    print(f"\n# {platforms}")
    for hour in range(args.start, end + 1):
        print(f"0 {hour} {d} {m} * cd {DIR} && {PYTHON} caption-automation/poster.py{yt_flag} >> output/cron.log 2>&1")
    print()

if __name__ == "__main__":
    main()
