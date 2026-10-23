"""Turn measurements into CSV files, plots and a Markdown summary."""

import csv
import math
from pathlib import Path
from statistics import mean

import matplotlib

matplotlib.use("Agg")   # draw to files only; no window is opened
import matplotlib.pyplot as plt  # noqa: E402  (must come after choosing the backend)

from bully.communication import ARE_YOU_NORMAL, ARE_YOU_THERE, HALT, NEW_COORDINATOR, READY  # noqa: E402

from .measure import UDP_INTERVAL, UDP_SCENARIOS, UDP_TIMEOUT, Measurement  # noqa: E402
from .scenarios import SCENARIOS  # noqa: E402

ALGORITHM_NAMES = ("original", "improved")
MESSAGE_NAMES = (ARE_YOU_THERE, ARE_YOU_NORMAL, HALT, NEW_COORDINATOR, READY)
STYLE = {"original": dict(color="tab:blue", marker="o"), "improved": dict(color="tab:orange", marker="s")}


# --- CSV ---


def write_csv(measurements: list[Measurement], path: Path) -> None:
    columns = [
        "algorithm", "scenario", "n", "repetition", "total", "election_messages",
        "detection_messages", *MESSAGE_NAMES, "unanswered", "rounds", "leader_calls",
        "elections", "seconds", "correct_leader",
    ]
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        for m in measurements:
            writer.writerow({
                "algorithm": m.algorithm, "scenario": m.scenario, "n": m.n,
                "repetition": m.repetition, "total": m.total,
                "election_messages": m.election_messages,
                "detection_messages": m.detection_messages,
                **{kind: m.messages[kind] for kind in MESSAGE_NAMES},
                "unanswered": m.unanswered, "rounds": m.rounds, "leader_calls": m.leader_calls,
                "elections": m.elections,
                "seconds": None if m.seconds is None else round(m.seconds, 4),
                "correct_leader": m.correct_leader,
            })


# --- Plots ---


def _select(measurements, algorithm, scenario):
    return sorted((m for m in measurements if m.algorithm == algorithm and m.scenario == scenario),
                  key=lambda m: m.n)


def plot_in_memory(measurements: list[Measurement], path: Path, value, ylabel: str, scenarios,
                   columns: int = 4) -> None:
    """One small plot per scenario: value(measurement) against n, one line per algorithm."""
    rows = math.ceil(len(scenarios) / columns)
    figure, axes = plt.subplots(rows, columns, figsize=(4 * columns, 3.2 * rows), squeeze=False)
    for ax, scenario in zip(axes.flat, scenarios):
        for algorithm in ALGORITHM_NAMES:
            points = _select(measurements, algorithm, scenario.name)
            ax.plot([m.n for m in points], [value(m) for m in points], label=algorithm, **STYLE[algorithm])
        ax.set_title(scenario.name)
        ax.set_xlabel("n (nodes)")
        ax.set_ylabel(ylabel)
        ax.grid(alpha=0.3)
    for ax in list(axes.flat)[len(scenarios):]:
        ax.axis("off")
    axes.flat[0].legend()
    figure.tight_layout()
    figure.savefig(path, dpi=120)
    plt.close(figure)


def plot_udp(measurements: list[Measurement], path: Path) -> None:
    """Messages and seconds against n, mean over the repetitions with min-max bars."""
    figure, axes = plt.subplots(len(UDP_SCENARIOS), 2, figsize=(10, 3.4 * len(UDP_SCENARIOS)), squeeze=False)
    for row, scenario in zip(axes, UDP_SCENARIOS):
        for ax, (value, ylabel) in zip(row, [(lambda m: m.total, "messages"), (lambda m: m.seconds, "seconds")]):
            for algorithm in ALGORITHM_NAMES:
                sizes, means, low, high = [], [], [], []
                for n, group in _group_by_n(_select(measurements, algorithm, scenario)).items():
                    values = [value(m) for m in group]
                    sizes.append(n)
                    means.append(mean(values))
                    low.append(mean(values) - min(values))
                    high.append(max(values) - mean(values))
                ax.errorbar(sizes, means, yerr=[low, high], capsize=3, label=algorithm, **STYLE[algorithm])
            ax.set_title(f"{scenario} (UDP)")
            ax.set_xlabel("n (nodes)")
            ax.set_ylabel(ylabel)
            ax.grid(alpha=0.3)
    axes[0][0].legend()
    figure.tight_layout()
    figure.savefig(path, dpi=120)
    plt.close(figure)


def _group_by_n(measurements):
    groups = {}
    for m in measurements:
        groups.setdefault(m.n, []).append(m)
    return dict(sorted(groups.items()))


# --- Summary ---


def growth_exponent(measurements, algorithm, scenario, value=lambda m: m.total) -> float | None:
    """k such that the cost grows like n^k, estimated from n = 10 and the largest n."""
    points = {m.n: value(m) for m in _select(measurements, algorithm, scenario)}
    largest = max(points)
    if 10 not in points or largest <= 10 or points[10] <= 0:
        return None
    return math.log(points[largest] / points[10]) / math.log(largest / 10)


def summary(in_memory: list[Measurement], udp: list[Measurement], repetitions: int) -> str:
    sizes = sorted({m.n for m in in_memory})
    shown = [n for n in (10, sizes[-1]) if n in sizes] or sizes[-1:]
    lines = [
        "# Experiment results",
        "",
        "Generated by `python -m experiments.run`. Every number below is in `in_memory.csv` and `udp.csv`.",
        "",
        "## Scenarios",
        "",
        "| Scenario | What happens |",
        "|---|---|",
        *(f"| {s.name} | {s.description} |" for s in SCENARIOS),
        "",
        f"## Messages per scenario (in memory, exact; n = {', '.join(map(str, shown))})",
        "",
        "Election messages are Halt, NewCoordinator and Ready; detection messages are AreYouThere and",
        "AreYouNormal. Leader calls are the calls the final leader made one after another, each taking",
        "at most T, so the election takes at most that many T.",
        "",
        "| Scenario | n | Messages (original -> improved) | Saved | Election msgs | Detection msgs "
        "| Unanswered | Leader calls | Elections |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for scenario in SCENARIOS:
        for n in shown:
            o, i = (_one(in_memory, a, scenario.name, n) for a in ALGORITHM_NAMES)
            saved = f"{1 - i.total / o.total:.0%}" if o.total else "-"
            lines.append(
                f"| {scenario.name} | {n} | {o.total} -> {i.total} | {saved} "
                f"| {o.election_messages} -> {i.election_messages} "
                f"| {o.detection_messages} -> {i.detection_messages} "
                f"| {o.unanswered} -> {i.unanswered} | {o.leader_calls} -> {i.leader_calls} "
                f"| {o.elections} -> {i.elections} |"
            )

    lines += [
        "",
        f"## How the cost grows with n (from n = 10 to n = {sizes[-1]})",
        "",
        "The total number of messages grows like n^k:",
        "",
        "| Scenario | Original | Improved |",
        "|---|---|---|",
    ]
    for scenario in SCENARIOS:
        exponents = [growth_exponent(in_memory, a, scenario.name) for a in ALGORITHM_NAMES]
        cells = ["-" if k is None else f"n^{k:.2f}" for k in exponents]
        lines.append(f"| {scenario.name} | {cells[0]} | {cells[1]} |")

    if udp:
        lines += [
            "",
            f"## Concurrent runs over UDP (T = {UDP_TIMEOUT} s, check interval {UDP_INTERVAL} s, "
            f"{repetitions} repetitions)",
            "",
            "Every node runs in its own thread on real sockets, so elections overlap. "
            "Mean (min-max) per run.",
            "",
            "| Scenario | n | Messages, original | Messages, improved | Seconds, original | Seconds, improved |",
            "|---|---|---|---|---|---|",
        ]
        for scenario in UDP_SCENARIOS:
            for n in sorted({m.n for m in udp}):
                cells = []
                for value, digits in ((lambda m: m.total, 1), (lambda m: m.seconds, 2)):
                    for algorithm in ALGORITHM_NAMES:
                        values = [value(m) for m in _select(udp, algorithm, scenario) if m.n == n]
                        cells.append(f"{mean(values):.{digits}f} ({min(values):.{digits}f}-{max(values):.{digits}f})")
                lines.append(f"| {scenario} | {n} | " + " | ".join(cells) + " |")

    everything = in_memory + udp
    checks = sum(m.safety_checks for m in in_memory)
    correct = sum(m.correct_leader for m in everything)
    lines += [
        "",
        "## Correctness",
        "",
        f"- Assertion 1 (safety) was checked {checks:,} times during the in-memory runs, "
        "after every state change of every node. It never failed.",
        f"- {correct} of {len(everything)} runs ended with every live node agreeing on the highest "
        "live node (Assertion 2, and the expected leader).",
        "",
    ]
    return "\n".join(lines)


def _one(measurements, algorithm, scenario, n):
    return next(m for m in measurements if (m.algorithm, m.scenario, m.n) == (algorithm, scenario, n))
