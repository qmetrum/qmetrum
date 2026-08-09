from __future__ import annotations

import argparse
import sys

from .orchestrator import run_lens


def _print(v) -> None:
    print(f"\n=== QLens - {v.ticker} - {v.as_of} ===")
    print(f"STANCE: {v.stance}   (conviction: {v.conviction})\n")
    print("Bull case:")
    for x in v.bull:
        print(f"  + {x}")
    print("\nBear case:")
    for x in v.bear:
        print(f"  - {x}")
    if v.key_risks:
        print("\nKey risks:")
        for x in v.key_risks:
            print(f"  ! {x}")
    if v.what_would_change_my_mind:
        print("\nWhat would change my mind:")
        for x in v.what_would_change_my_mind:
            print(f"  ~ {x}")
    if v.rationale:
        print(f"\nRationale: {v.rationale}")
    print(f"\n{v.disclaimer}\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="QLens - decision-support research lens")
    ap.add_argument("ticker")
    ap.add_argument("--context", default=None, help="extra context to weigh (freeform)")
    args = ap.parse_args(argv)
    _print(run_lens(args.ticker, extra_context=args.context))
    return 0


if __name__ == "__main__":
    sys.exit(main())
