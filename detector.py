"""Score every operator's activity on the review day against their own normal, and rank the most unusual."""
import sqlite3

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

OFF_HOURS = lambda h: (h < 7) | (h >= 19)
RISK_FLOOR, RISK_TOP = 0.45, 0.80    # model scores mapped to risk 0 and 100

# metric -> (minimum spread used for its baseline, plain label)
METRICS = {
    "enrol_count":      (2.5, "enrolments"),
    "enrol_off_hours":  (0.5, "enrolments outside working hours"),
    "quality_sameness": (1.5, "near-identical fingerprint quality scores"),
    "avg_retries":      (0.5, "capture retries per enrolment"),
    "kyc_incomplete":   (1.0, "enrolments with incomplete KYC"),
    "foreign_device":   (0.5, "enrolments on another branch's device"),
    "verif_fail_rate":  (0.06, "failed fingerprint verifications"),
    "verif_off_hours":  (0.5, "verifications outside working hours"),
    "detach_count":     (0.7, "fingerprint detaches"),
    "detach_no_reason": (0.5, "detaches with no reason given"),
}


def load(con):
    q = lambda sql: pd.read_sql_query(sql, con, parse_dates=["ts"])
    e = q("SELECT e.*, d.branch_code AS device_branch FROM enrolments e JOIN devices d USING (device_code)")
    v = q("SELECT * FROM verifications")
    x = q("SELECT * FROM detaches")
    for df in (e, v, x):
        df["day"] = df["ts"].dt.date.astype(str)
        df["hour"] = df["ts"].dt.hour
    return e, v, x


def daily_metrics(e, v, x):
    eg = e.assign(off=OFF_HOURS(e["hour"]), kyc_n=e["kyc_complete"].eq("N"),
                  foreign=e["device_branch"].ne(e["branch_code"])) \
        .groupby(["operator_code", "day"]).agg(
            enrol_count=("id", "size"), enrol_off_hours=("off", "sum"), q_std=("quality_score", "std"),
            avg_retries=("capture_retries", "mean"), kyc_incomplete=("kyc_n", "sum"),
            foreign_device=("foreign", "sum"))
    vg = v.assign(off=OFF_HOURS(v["hour"]), fail=v["result"].eq("FAIL")) \
        .groupby(["operator_code", "day"]).agg(
            verif_count=("id", "size"), verif_fails=("fail", "sum"), verif_off_hours=("off", "sum"))
    xg = x.assign(nr=x["reason_given"].eq("N")).groupby(["operator_code", "day"]).agg(
        detach_count=("id", "size"), detach_no_reason=("nr", "sum"))
    m = eg.join(vg, how="outer").join(xg, how="outer").reset_index()
    counts = ["enrol_count", "enrol_off_hours", "kyc_incomplete", "foreign_device", "verif_count",
              "verif_fails", "verif_off_hours", "detach_count", "detach_no_reason"]
    m[counts] = m[counts].fillna(0)
    m["avg_retries"] = m["avg_retries"].fillna(0)
    m["verif_fail_rate"] = np.where(m["verif_count"] >= 5, m["verif_fails"] / m["verif_count"].clip(lower=1), np.nan)
    # low spread of quality scores = captures that look copied; only meaningful with 5+ captures
    m["q_std"] = np.where(m["enrol_count"] >= 5, m["q_std"], np.nan)
    return m


def score(con, review_day):
    e, v, x = load(con)
    m = daily_metrics(e, v, x)
    m = m[m["day"] <= review_day]          # checking a past date never looks at what came after it
    hist = m[m["day"] < review_day]

    # each operator's normal, from their own history
    base = hist.groupby("operator_code").agg(
        **{f"{k}_mean": (k, "mean") for k in METRICS if k != "quality_sameness"},
        **{f"{k}_std": (k, "std") for k in METRICS if k != "quality_sameness"},
        q_std_mean=("q_std", "mean"), q_std_std=("q_std", "std"), days_worked=("day", "nunique"))
    m = m.merge(base, on="operator_code", how="left")

    z = pd.DataFrame(index=m.index)
    for k, (floor, _) in METRICS.items():
        if k == "quality_sameness":
            # how many times tighter than this operator's usual spread of quality scores (copied captures)
            z[k] = (m["q_std_mean"] / m["q_std"].clip(lower=0.75) - 1.5).fillna(0)
        else:
            mean = m[f"{k}_mean"].fillna(0)
            spread = np.maximum(m[f"{k}_std"].fillna(floor), np.maximum(floor, 0.25 * mean))
            z[k] = ((m[k].fillna(mean) - mean) / spread).fillna(0)
    z = z.clip(lower=0, upper=15)                      # only "more unusual than normal" counts

    # every tree sees every day, so rare signals (e.g. a foreign device) are not sampled away
    model = IsolationForest(n_estimators=300, max_samples=len(z), random_state=42).fit(z.values)
    raw = -model.score_samples(z.values)
    # a fixed scale, so a risk of 60 means the same on a quiet day as on a busy one
    # (an ordinary day scores about 0.35 on the model's own 0-1 scale)
    m["risk"] = np.clip(np.round(100 * (raw - RISK_FLOOR) / (RISK_TOP - RISK_FLOOR)), 0, 100).astype(int)
    m["strongest"] = z.max(axis=1)

    today = m["day"].eq(review_day)
    out = m[today].copy()
    out_z = z[today]
    records = int(len(e[e["day"] == review_day]) + len(v[v["day"] == review_day]) + len(x[x["day"] == review_day]))
    return out, out_z, records, (e, v, x)


def build_facts(row, zrow, e, v, x, review_day):
    """The checked facts behind one case: what happened against the operator's normal."""
    op = row["operator_code"]
    signals = []
    ranked = zrow.sort_values(ascending=False)
    # strong signals first; a borderline case still gets its two mildest-but-real reasons
    threshold = 2.0 if ranked.iloc[0] >= 2.0 else 0.8
    for k in ranked.index:
        if ranked[k] < threshold or len(signals) == (3 if threshold == 2.0 else 2):
            break
        s = {"key": k, "label": METRICS[k][1]}
        if k == "enrol_count":
            usual = hist_median(e, op, row["day"])
            s.update(today=int(row[k]), normal=usual)
            if usual:
                s["times"] = int(row[k] // usual)
        elif k in ("enrol_off_hours", "verif_off_hours"):
            src = e if k == "enrol_off_hours" else v
            t = src[(src["operator_code"] == op) & (src["day"] == review_day) & OFF_HOURS(src["hour"])]["ts"]
            s.update(today=int(row[k]), start=t.min().strftime("%H:%M"), end=t.max().strftime("%H:%M"))
        elif k == "quality_sameness":
            q = e[(e["operator_code"] == op) & (e["day"] == review_day)]["quality_score"]
            if q.max() - q.min() > 6:          # not genuinely "almost identical": don't claim it
                continue
            s.update(today=int(row["enrol_count"]), low=int(q.min()), high=int(q.max()))
        elif k == "avg_retries":
            s.update(today=round(row[k], 1), normal=round(row["avg_retries_mean"], 1))
        elif k == "kyc_incomplete":
            s.update(today=int(row[k]), of=int(row["enrol_count"]))
        elif k == "foreign_device":
            dev = e[(e["operator_code"] == op) & (e["day"] == review_day) &
                    e["device_branch"].ne(e["branch_code"])]
            s.update(today=int(row[k]), device=dev["device_code"].iloc[0], device_branch=dev["device_branch"].iloc[0])
        elif k == "verif_fail_rate":
            s.update(today=int(row["verif_fails"]), of=int(row["verif_count"]),
                     normal_pct=round(100 * row["verif_fail_rate_mean"]))
        elif k == "detach_count":
            s.update(today=int(row[k]), normal_month=int(round(row["detach_count_mean"] * row["days_worked"])))
        elif k == "detach_no_reason":
            s.update(today=int(row[k]))
        signals.append(s)
    return {"operator": op, "branch": row_branch(e, v, op), "date": review_day,
            "risk": int(row["risk"]), "signals": signals}


def hist_median(e, op, review_day):
    """An operator's typical enrolments on a day they work (the median, so half-day Saturdays don't drag it down)."""
    days = e[(e["operator_code"] == op) & (e["day"] < review_day)].groupby("day").size()
    return int(days.median()) if len(days) else 0


def row_branch(e, v, op):
    b = e.loc[e["operator_code"] == op, "branch_code"]
    return b.iloc[0] if len(b) else v.loc[v["operator_code"] == op, "branch_code"].iloc[0]


MIN_RISK = 35        # below this, activity is ordinary day-to-day variation
MIN_SIGNAL = 2.0     # a case is listed only if at least one reason is clearly outside normal


def top_cases(con, review_day, n=20):
    out, out_z, records, (e, v, x) = score(con, review_day)
    out = out[(out["risk"] >= MIN_RISK) & (out["strongest"] >= MIN_SIGNAL)] \
        .sort_values(["risk", "strongest"], ascending=False).head(n)
    cases = [build_facts(r, out_z.loc[i], e, v, x, review_day) for i, r in out.iterrows()]
    operators = int(len(set(e.loc[e["day"] == review_day, "operator_code"]) |
                        set(v.loc[v["day"] == review_day, "operator_code"])))
    return cases, records, operators


if __name__ == "__main__":
    con = sqlite3.connect("demo.db")
    cases, records, ops = top_cases(con, "2026-10-06")
    print(records, "records,", ops, "operators")
    for i, c in enumerate(cases, 1):
        print(i, c["operator"], c["branch"], c["risk"], [(s["key"], s.get("today")) for s in c["signals"]])
