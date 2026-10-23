"""Run all experiments and write the results to results/.

    python -m experiments.run              everything (about three minutes)
    python -m experiments.run --no-udp     only the in-memory runs (about a second)

Writes in_memory.csv, udp.csv, messages.png, election_time.png, udp.png and summary.md,
and prints the summary.
"""

import argparse
from pathlib import Path

from .measure import UDP_SCENARIOS, measure_in_memory, measure_over_udp
from .report import (
    ALGORITHM_NAMES,
    plot_in_memory,
    plot_udp,
    summary,
    write_csv,
)
from .scenarios import SCENARIOS

SIZES = [2, 3, 5, 10, 20, 30, 40, 50]   # n for the in-memory runs
UDP_SIZES = [3, 5, 8, 12, 16]            # n for the UDP runs (one thread pair per node)
REPETITIONS = 5                          # UDP runs vary, so each one is repeated

# The scenarios whose election time is plotted: each ends with one election by one leader.
TIMED = ("first election", "coordinator crash", "crash, one detector", "half crash", "coordinator returns")


def run(out_dir: Path, sizes=SIZES, udp_sizes=UDP_SIZES, repetitions=REPETITIONS) -> str:
    in_memory = [
        measure_in_memory(algorithm, scenario, n)
        for scenario in SCENARIOS
        for n in sizes
        for algorithm in ALGORITHM_NAMES
    ]

    udp = []
    for scenario in UDP_SCENARIOS:
        for n in udp_sizes:
            print(f"over UDP: {scenario}, n = {n}", flush=True)
            for algorithm in ALGORITHM_NAMES:
                udp += [measure_over_udp(algorithm, scenario, n, r) for r in range(repetitions)]

    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(in_memory, out_dir / "in_memory.csv")
    plot_in_memory(in_memory, out_dir / "messages.png", lambda m: m.total, "messages", SCENARIOS)
    plot_in_memory(in_memory, out_dir / "election_time.png", lambda m: m.leader_calls,
                   "leader calls (x T)", [s for s in SCENARIOS if s.name in TIMED], columns=len(TIMED))
    if udp:
        write_csv(udp, out_dir / "udp.csv")
        plot_udp(udp, out_dir / "udp.png")

    text = summary(in_memory, udp, repetitions)
    (out_dir / "summary.md").write_text(text, encoding="utf-8")
    return text


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Compare the original and the improved Bully algorithm.")
    parser.add_argument("--out", type=Path, default=Path("results"), help="output folder (default: results)")
    parser.add_argument("--no-udp", action="store_true", help="skip the concurrent runs over UDP")
    parser.add_argument("--repetitions", type=int, default=REPETITIONS, help="repetitions per UDP run")
    args = parser.parse_args(argv)
    print(run(args.out, udp_sizes=[] if args.no_udp else UDP_SIZES, repetitions=args.repetitions))


if __name__ == "__main__":
    main()
