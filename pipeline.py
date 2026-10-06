"""The nightly check: read yesterday's activity, score it, explain the top cases, save the review queue."""
import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import detector
import explainer

DB = Path(__file__).with_name("demo.db")
REVIEW_DAY = "2026-10-06"


def now():
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def audit(con, event, detail=""):
    con.execute("INSERT INTO audit_log (ts, event, detail) VALUES (?,?,?)", (now(), event, detail))


def connect():
    # wait for a busy database instead of failing at once
    return sqlite3.connect(DB, timeout=30)


class AlreadyRunning(Exception):
    pass


def running():
    """True if another check started in the last 10 minutes and has not finished."""
    with connect() as con:
        r = con.execute("SELECT 1 FROM runs WHERE finished_at IS NULL"
                        " AND started_at > datetime('now', 'localtime', '-10 minutes')").fetchone()
    return r is not None


def run(review_day=REVIEW_DAY, progress=lambda step, frac: None):
    if running():
        raise AlreadyRunning("A check is already running. Wait for it to finish.")
    con = connect()
    t0, started = time.time(), now()
    run_id = con.execute("INSERT INTO runs (review_date, started_at) VALUES (?,?)", (review_day, started)).lastrowid
    audit(con, "Nightly check started", f"Reviewing activity for {review_day}")
    con.commit()

    progress("Reading yesterday's activity and learning each operator's normal pattern", 0.05)
    cases, records, operators = detector.top_cases(con, review_day)
    con.execute("UPDATE runs SET records_checked=?, operators_checked=? WHERE run_id=?", (records, operators, run_id))
    con.commit()
    progress(f"Scored {records:,} records from {operators} operators", 0.25)

    for i, facts in enumerate(cases, 1):
        progress(f"Writing the explanation for case {i} of {len(cases)} ({facts['operator']})",
                 0.25 + 0.75 * (i - 1) / max(len(cases), 1))
        sentence, source, draft = explainer.explain(facts)      # slow: no database lock held here
        con.execute("INSERT INTO review_queue VALUES (?,?,?,?,?,?,?,?,?)",
                    (run_id, i, facts["operator"], facts["branch"], facts["risk"], json.dumps(facts),
                     sentence, source, draft))
        audit(con, "Case flagged", f"{facts['operator']} ({facts['branch']}), risk {facts['risk']}: {sentence}")
        if source.startswith("template (AI draft"):
            audit(con, "AI sentence rejected by fact check", f"{facts['operator']}: {source[19:-1]}")
        con.commit()
    secs = round(time.time() - t0, 1)
    con.execute("UPDATE runs SET finished_at=?, seconds_taken=? WHERE run_id=?", (now(), secs, run_id))
    audit(con, "Nightly check finished", f"{records:,} records checked, {len(cases)} cases to review, {secs}s")
    con.commit()
    con.close()
    progress("Done", 1.0)
    return run_id


if __name__ == "__main__":
    # python pipeline.py            -> check every demo day
    # python pipeline.py 2026-10-05 -> check one day
    import sys
    print("Ollama ready:", explainer.ollama_ready())
    with connect() as con:
        days = sys.argv[1:] or [d for (d,) in con.execute("SELECT day FROM review_days ORDER BY day")]
    for day in days:
        print(f"\n=== {day} ===")
        rid = run(day, progress=lambda s, f: print(f"[{f:4.0%}] {s}"))
        with connect() as con:
            for row in con.execute("SELECT rank, operator_code, risk, sentence_source, sentence FROM review_queue"
                                   " WHERE run_id=? ORDER BY rank", (rid,)):
                print(row)
