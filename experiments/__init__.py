"""Comparative experiments: the original Bully algorithm against the improved variant.

Run all of them with `python -m experiments.run`; the results go to results/.

    scenarios.py  the failure scenarios, run on an in-memory cluster
    measure.py    one measurement: in memory (exact counts) or over UDP (concurrent, timed)
    report.py     the CSV files, the plots and the summary tables
    run.py        runs everything
"""
