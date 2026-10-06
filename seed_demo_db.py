"""Create demo.db: 30 days of realistic, fully coded COMPAS-style activity.

Only coded IDs and numbers are stored - no names, ID numbers, images or templates.
Suspicious cases are planted on three review days (2, 5 and 6 Oct) so the demo can show them being found.
"""
import random
import sqlite3
from datetime import date, datetime, time, timedelta
from pathlib import Path

DB = Path(__file__).with_name("demo.db")
START = date(2026, 9, 7)
REVIEW_DAY = date(2026, 10, 6)          # last day of data; "yesterday" on demo day, 7 Oct 2026
N_BRANCHES, OPS_PER_BRANCH = 12, 8      # 96 operators
rng = random.Random(7)

SCHEMA = """
CREATE TABLE branches (branch_code TEXT PRIMARY KEY, region TEXT, size TEXT);
CREATE TABLE operators (operator_code TEXT PRIMARY KEY, branch_code TEXT, main_device TEXT);
CREATE TABLE devices (device_code TEXT PRIMARY KEY, branch_code TEXT);
CREATE TABLE enrolments (id INTEGER PRIMARY KEY, operator_code TEXT, branch_code TEXT, device_code TEXT,
    ts TEXT, quality_score INTEGER, capture_retries INTEGER, kyc_complete TEXT);
CREATE TABLE verifications (id INTEGER PRIMARY KEY, operator_code TEXT, branch_code TEXT, device_code TEXT,
    ts TEXT, quality_score INTEGER, attempts INTEGER, result TEXT);
CREATE TABLE detaches (id INTEGER PRIMARY KEY, operator_code TEXT, branch_code TEXT, ts TEXT, reason_given TEXT);
CREATE TABLE runs (run_id INTEGER PRIMARY KEY, review_date TEXT, started_at TEXT, finished_at TEXT,
    records_checked INTEGER, operators_checked INTEGER, seconds_taken REAL);
CREATE TABLE review_queue (run_id INTEGER, rank INTEGER, operator_code TEXT, branch_code TEXT, risk INTEGER,
    facts_json TEXT, sentence TEXT, sentence_source TEXT, draft TEXT);
CREATE TABLE decisions (id INTEGER PRIMARY KEY, run_id INTEGER, operator_code TEXT, decision TEXT,
    reviewer TEXT, ts TEXT);
CREATE TABLE audit_log (id INTEGER PRIMARY KEY, ts TEXT, event TEXT, detail TEXT);
CREATE TABLE review_days (day TEXT PRIMARY KEY, note TEXT);
"""

SIZES = {"large": 12, "medium": 8, "small": 4}   # normal enrolments per operator per day


def ts(d, h, m, s=0):
    return datetime.combine(d, time(h, m, s)).isoformat(sep=" ")


def work_time(d, shift_start, shift_end):
    """A random time in the operator's shift, thinner over lunch."""
    while True:
        minute = rng.uniform(shift_start * 60, shift_end * 60)
        if 12.75 * 60 <= minute <= 13.75 * 60 and rng.random() < 0.6:
            continue
        return ts(d, int(minute // 60), int(minute % 60), rng.randint(0, 59))


def clip(v, lo, hi):
    return max(lo, min(hi, int(round(v))))


def main():
    con = sqlite3.connect(DB, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")     # the portal can read while the nightly check writes
    # clear tables rather than deleting the file, so a reset works while the portal is open
    for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        con.execute(f"DROP TABLE {t}")
    con.executescript(SCHEMA)

    sizes = ["large", "large", "medium", "medium", "medium", "medium", "medium",
             "small", "small", "small", "small", "small"]
    regions = ["Central", "Central", "Central", "Western", "Western", "Eastern",
               "Eastern", "Northern", "Northern", "Central", "Western", "Eastern"]
    ops = []
    for b in range(1, N_BRANCHES + 1):
        bc = f"BR_{b:02d}"
        con.execute("INSERT INTO branches VALUES (?,?,?)", (bc, regions[b - 1], sizes[b - 1]))
        for d in range(1, OPS_PER_BRANCH + 3):           # operator devices + 2 spares per branch
            con.execute("INSERT INTO devices VALUES (?,?)", (f"DV_{b:02d}{d:02d}", bc))
        for k in range(OPS_PER_BRANCH):
            n = (b - 1) * OPS_PER_BRANCH + k + 1
            oc, dev = f"OP_{n:03d}", f"DV_{b:02d}{k + 1:02d}"
            con.execute("INSERT INTO operators VALUES (?,?,?)", (oc, bc, dev))
            ops.append(dict(
                code=oc, branch=bc, b=b, device=dev,
                enrol_mean=SIZES[sizes[b - 1]] * rng.uniform(0.75, 1.25),
                verif_mean=SIZES[sizes[b - 1]] * rng.uniform(2.5, 3.5),
                q_mean=rng.uniform(66, 80), fail_rate=rng.uniform(0.02, 0.06),
                start=rng.uniform(8.0, 9.25), end=rng.uniform(15.75, 17.0)))

    # OP_017 matches the example in the brief: about 8 enrolments a day, 9am to 4pm
    op17 = next(o for o in ops if o["code"] == "OP_017")
    op17.update(enrol_mean=8.0, start=9.0, end=16.0)

    enrol, verif, detach = [], [], []
    day = START
    while day <= REVIEW_DAY:
        wd = day.weekday()
        if wd == 6:                                   # branches closed on Sunday
            day += timedelta(days=1)
            continue
        load = 0.5 if wd == 5 else 1.0
        for o in ops:
            if rng.random() < 0.05:                   # leave / off day
                continue
            end = 12.5 if wd == 5 else o["end"]
            for _ in range(poisson(o["enrol_mean"] * load)):
                dev = o["device"] if rng.random() > 0.04 else f"DV_{o['b']:02d}{OPS_PER_BRANCH + 1:02d}"
                enrol.append((o["code"], o["branch"], dev, work_time(day, o["start"], end),
                              clip(rng.gauss(o["q_mean"], 9), 35, 99), poisson(0.6),
                              "N" if rng.random() < 0.03 else "Y"))
            for _ in range(poisson(o["verif_mean"] * load)):
                failed = rng.random() < o["fail_rate"]
                verif.append((o["code"], o["branch"], o["device"], work_time(day, o["start"], end),
                              clip(rng.gauss(o["q_mean"] - (15 if failed else 0), 10), 20, 99),
                              rng.choice([2, 3, 3]) if failed else rng.choice([1, 1, 1, 2]),
                              "FAIL" if failed else "PASS"))
            if rng.random() < 0.02:
                detach.append((o["code"], o["branch"], work_time(day, o["start"], end),
                               "Y" if rng.random() < 0.95 else "N"))
        day += timedelta(days=1)

    by_code = {o["code"]: o for o in ops}
    for d, (note, scenario) in SCENARIOS.items():
        plant(d, scenario, by_code, enrol, verif, detach)
        con.execute("INSERT INTO review_days VALUES (?,?)", (d.isoformat(), note))

    con.executemany("INSERT INTO enrolments (operator_code, branch_code, device_code, ts, quality_score,"
                    " capture_retries, kyc_complete) VALUES (?,?,?,?,?,?,?)", enrol)
    con.executemany("INSERT INTO verifications (operator_code, branch_code, device_code, ts, quality_score,"
                    " attempts, result) VALUES (?,?,?,?,?,?,?)", verif)
    con.executemany("INSERT INTO detaches (operator_code, branch_code, ts, reason_given) VALUES (?,?,?,?)", detach)
    con.execute("INSERT INTO audit_log (ts, event, detail) VALUES (?,?,?)",
                (datetime.now().isoformat(sep=" ", timespec="seconds"), "Demo data created",
                 f"{len(enrol):,} enrolments, {len(verif):,} verifications, {len(detach)} detaches"))
    con.commit()
    con.close()
    print(f"demo.db created: {len(enrol):,} enrolments, {len(verif):,} verifications, {len(detach)} detaches")


def poisson(lam):
    # Knuth's method; fine for the small means used here
    L, k, p = pow(2.718281828, -lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


def at(day, h, m, seconds_after=0):
    return (datetime.combine(day, time(h, m)) + timedelta(seconds=seconds_after)).isoformat(sep=" ")


def plant(day, scenario, ops, enrol, verif, detach):
    """Replace some operators' activity on one review day with suspicious patterns."""
    d = day.isoformat()
    planted = {op for op, *_ in scenario}
    enrol[:] = [r for r in enrol if not (r[0] in planted and r[3].startswith(d))]
    verif[:] = [r for r in verif if not (r[0] in planted and r[3].startswith(d))]
    detach[:] = [r for r in detach if not (r[0] in planted and r[2].startswith(d))]

    def normal_enrol(o, n):
        for _ in range(n):
            enrol.append((o["code"], o["branch"], o["device"], work_time(day, o["start"], o["end"]),
                          clip(rng.gauss(o["q_mean"], 9), 35, 99), poisson(0.6), "Y"))

    def normal_verif(o, n):
        for _ in range(n):
            verif.append((o["code"], o["branch"], o["device"], work_time(day, o["start"], o["end"]),
                          clip(rng.gauss(o["q_mean"], 10), 20, 99), 1, "PASS"))

    for op, kind, p in scenario:
        o = ops[op]
        normal_verif(o, poisson(o["verif_mean"]))          # verifications carry on as usual unless replaced below
        if kind == "night_enrolments":                    # a burst of enrolments outside working hours
            n, (h, m), mins = p["n"], p["start"], p["minutes"]
            for i in range(n):
                q = rng.choice(p["quality"]) if "quality" in p else clip(rng.gauss(o["q_mean"], 9), 35, 99)
                enrol.append((op, o["branch"], o["device"], at(day, h, m, round(60 * mins * i / (n - 1))), q, 0, "Y"))
        elif kind == "late_failed_verifications":         # verifications late at night, most of them failing
            normal_enrol(o, poisson(o["enrol_mean"]))
            (h, m) = p["start"]
            for i in range(p["n"]):
                failed = i % 10 < p["fail_in_10"]
                verif.append((op, o["branch"], o["device"], at(day, h, m, 90 * i),
                              rng.randint(25, 45) if failed else rng.randint(60, 75),
                              rng.choice([3, 4, 5]) if failed else 1, "FAIL" if failed else "PASS"))
        elif kind == "daytime_failed_verifications":      # an unusual share of verifications failing in working hours
            normal_enrol(o, poisson(o["enrol_mean"]))
            verif[:] = [r for r in verif if not (r[0] == op and r[3].startswith(d))]
            for i in range(p["n"]):
                failed = i < p["fails"]
                verif.append((op, o["branch"], o["device"], work_time(day, o["start"], o["end"]),
                              rng.randint(25, 45) if failed else clip(rng.gauss(o["q_mean"], 10), 20, 99),
                              rng.choice([3, 4]) if failed else 1, "FAIL" if failed else "PASS"))
        elif kind == "identical_quality":                 # captures whose quality scores look copied
            for _ in range(p["n"]):
                enrol.append((op, o["branch"], o["device"], work_time(day, o["start"], o["end"]),
                              rng.choice(p["quality"]), 0, "Y"))
        elif kind == "retries_and_kyc":                   # forced captures and KYC pushed through incomplete
            for i in range(p["n"]):
                enrol.append((op, o["branch"], o["device"], work_time(day, o["start"], o["end"]),
                              clip(rng.gauss(o["q_mean"] - 10, 8), 35, 99), rng.choice([4, 5, 5, 6]),
                              "N" if i < p["kyc_missing"] else "Y"))
        elif kind == "detach_burst":                      # many fingerprint detaches, few reasons given
            normal_enrol(o, poisson(o["enrol_mean"]))
            (h, m) = p["start"]
            for i in range(p["n"]):
                detach.append((op, o["branch"], at(day, h, m, 240 * i), "N" if i < p["no_reason"] else "Y"))
        elif kind == "foreign_device":                    # enrolments on another branch's device
            for _ in range(p["n"]):
                enrol.append((op, o["branch"], p["device"], work_time(day, o["start"], o["end"]),
                              clip(rng.gauss(o["q_mean"], 9), 35, 99), poisson(0.6), "Y"))
        else:
            raise ValueError(kind)


# What is planted on each demo day. Each day tells a different story; Friday is deliberately quiet.
SCENARIOS = {
    date(2026, 10, 2): ("Quiet day: two cases planted", [
        ("OP_076", "retries_and_kyc", dict(n=12, kyc_missing=8)),
        ("OP_009", "identical_quality", dict(n=12, quality=[77, 78, 78])),
    ]),
    date(2026, 10, 5): ("Four cases planted", [
        ("OP_090", "night_enrolments", dict(n=18, start=(22, 40), minutes=35)),
        ("OP_022", "daytime_failed_verifications", dict(n=45, fails=19)),
        ("OP_058", "detach_burst", dict(n=5, no_reason=5, start=(12, 10))),
        ("OP_036", "foreign_device", dict(n=7, device="DV_0709")),
    ]),
    date(2026, 10, 6): ("Busy day: six cases planted", [
        ("OP_017", "night_enrolments", dict(n=40, start=(1, 50), minutes=40, quality=[71, 72, 72, 73])),
        ("OP_032", "late_failed_verifications", dict(n=30, start=(23, 10), fail_in_10=7)),
        ("OP_081", "identical_quality", dict(n=14, quality=[84, 84, 85])),
        ("OP_014", "retries_and_kyc", dict(n=18, kyc_missing=11)),
        ("OP_063", "detach_burst", dict(n=6, no_reason=4, start=(16, 35))),
        ("OP_045", "foreign_device", dict(n=9, device="DV_0209")),
    ]),
}


if __name__ == "__main__":
    main()
