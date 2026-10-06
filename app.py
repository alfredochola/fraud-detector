"""Review portal for the AI-Powered Early Fraud Detection Engine (demo)."""
import html
import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

import explainer
import pipeline

DB = Path(__file__).with_name("demo.db")
SECONDS_PER_RECORD = 30          # assumption used for the manual-review estimate; shown on screen

st.set_page_config(page_title="Fraud Review Queue", page_icon="🛡️", layout="wide")
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@500;700;800&display=swap');
:root {
  --teal:#0D7666; --teal-dark:#0A3D37; --teal-tint:#E3F2EF;
  --high:#D9480F; --high-tint:#FFF1EA; --med:#D99A06; --med-tint:#FFF8E1; --low:#64748B; --low-tint:#F1F5F9;
  --ai:#5B4BDB; --ai-tint:#EEEBFF; --ink:#13202A; --muted:#5B6B78;
}
.block-container { padding-top: 3rem; max-width: 1200px; }
h1, h2, h3, h4, .display { font-family: 'Manrope', 'Source Sans 3', sans-serif !important; letter-spacing: -0.01em; }
h3 { font-weight: 800 !important; margin-top: 18px !important; }

/* header band */
.hero { background: linear-gradient(120deg, var(--teal-dark) 0%, var(--teal) 70%, #14A08A 100%);
  border-radius: 18px; padding: 26px 32px; color: #fff; margin-bottom: 18px; position: relative; overflow: hidden; }
.hero:after { content: ""; position: absolute; right: -60px; top: -60px; width: 260px; height: 260px;
  border-radius: 50%; background: rgba(255,255,255,.07); }
.hero .kicker { font-size: 13px; letter-spacing: .14em; text-transform: uppercase; opacity: .8; font-weight: 700; }
.hero h1 { color: #fff; font-size: 34px; font-weight: 800; margin: 4px 0 10px 0; padding: 0; line-height: 1.15; }
.hero .date { display: inline-block; background: rgba(255,255,255,.16); border: 1px solid rgba(255,255,255,.3);
  border-radius: 999px; padding: 5px 14px; font-weight: 700; font-size: 15px; }

/* number cards */
.kpis { display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 14px; margin: 4px 0 18px 0; }
.kpi { background: #fff; border: 1px solid #E2E8EE; border-radius: 16px; padding: 16px 18px; border-top: 5px solid var(--c); }
.kpi .label { font-size: 13px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; }
.kpi .value { font-family: 'Manrope', sans-serif; font-size: 38px; font-weight: 800; color: var(--c); line-height: 1.1; margin-top: 4px; }
.kpi .sub { font-size: 13px; color: var(--muted); margin-top: 2px; }
@media (max-width: 900px) { .kpis { grid-template-columns: repeat(2, minmax(0,1fr)); } }

/* reviewed progress */
.progress-row { display: flex; align-items: center; gap: 14px; margin: 0 0 14px 0; }
.progress-row .track { flex: 1; height: 10px; background: #E7EDF2; border-radius: 999px; overflow: hidden; }
.progress-row .fill { height: 100%; background: linear-gradient(90deg, var(--teal), #19B39A); border-radius: 999px; }
.progress-row .txt { font-weight: 700; color: var(--ink); font-size: 15px; white-space: nowrap; }

/* case cards: colour by risk level (containers are keyed case-high-*, case-med-*, case-low-*) */
div[class*="st-key-case-"] { border-radius: 16px !important; border: 1px solid #E2E8EE !important;
  border-left: 8px solid var(--c) !important; background: #fff; padding: 6px 8px 2px 8px; }
div[class*="st-key-case-high"] { --c: var(--high); background: linear-gradient(90deg, var(--high-tint), #fff 38%); }
div[class*="st-key-case-med"]  { --c: var(--med);  background: linear-gradient(90deg, var(--med-tint), #fff 38%); }
div[class*="st-key-case-low"]  { --c: var(--low);  background: linear-gradient(90deg, var(--low-tint), #fff 38%); }
.case-head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.rank { width: 34px; height: 34px; border-radius: 50%; background: var(--c); color: #fff; font-weight: 800;
  display: inline-flex; align-items: center; justify-content: center; font-size: 15px; }
.op { font-family: 'Manrope', sans-serif; font-weight: 800; font-size: 25px; color: var(--ink); }
.branch { background: #EEF2F5; color: var(--muted); border-radius: 8px; padding: 3px 10px; font-weight: 700; font-size: 13px; }
.risk { background: var(--c); color: #fff; border-radius: 999px; padding: 4px 14px; font-weight: 800; font-size: 13px;
  letter-spacing: .05em; text-transform: uppercase; }
.meter { width: 110px; height: 8px; background: #E7EDF2; border-radius: 999px; overflow: hidden; }
.meter > div { height: 100%; background: var(--c); }
.sentence { font-size: 19px; line-height: 1.55; color: var(--ink); margin: 12px 0 10px 0; }
.chip { display: inline-block; font-size: 13px; font-weight: 700; border-radius: 999px; padding: 3px 12px; margin: 0 6px 8px 0; }
.chip-ai { background: var(--ai-tint); color: var(--ai); }
.chip-tpl { background: #EEF2F5; color: var(--muted); }
.chip-inv { background: var(--teal); color: #fff; }
.chip-ok { background: #E7EDF2; color: var(--muted); }
.note { color: var(--muted); font-size: 14px; }

/* tabs */
[data-testid="stTab"] p { font-size: 18px !important; font-weight: 700 !important; }
[data-testid="stTab"] { padding: 10px 8px !important; }

/* sidebar */
section[data-testid="stSidebar"] { background: linear-gradient(180deg, var(--teal-dark), #0B5A50); }
section[data-testid="stSidebar"] * { color: #E9F5F2; }
section[data-testid="stSidebar"] input, section[data-testid="stSidebar"] [data-baseweb="select"] * { color: var(--ink) !important; }
section[data-testid="stSidebar"] .stButton button[kind="primary"] { background: #FFB020; border: 0; }
section[data-testid="stSidebar"] .stButton button[kind="primary"] p { color: #1B1300 !important; font-weight: 800; font-size: 16px; }
section[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,.15); }
.brand { font-family: 'Manrope', sans-serif; font-weight: 800; font-size: 22px; line-height: 1.2; }
.brand small { display: block; font-size: 12px; letter-spacing: .14em; text-transform: uppercase; opacity: .7; font-weight: 700; }
.status { display: inline-flex; align-items: center; gap: 8px; background: rgba(255,255,255,.1); border-radius: 999px;
  padding: 6px 12px; font-weight: 700; font-size: 14px; }
.dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
.side-label { font-size: 12px; letter-spacing: .12em; text-transform: uppercase; opacity: .75; font-weight: 700; margin: 6px 0 8px 0; }

/* data tab */
.panel { border-radius: 16px; padding: 18px 22px; height: 100%; }
.panel h4 { margin: 0 0 10px 0; font-size: 20px; }
.panel ul { list-style: none; padding: 0; margin: 0; }
.panel li { font-size: 16px; padding: 7px 0; border-bottom: 1px solid rgba(0,0,0,.06); }
.panel li:last-child { border-bottom: 0; }
.yes { background: var(--teal-tint); border: 1px solid #BFDFD8; }
.yes h4, .yes li:before { color: var(--teal); }
.no { background: var(--high-tint); border: 1px solid #F6CDB8; }
.no h4, .no li:before { color: var(--high); }
.yes li:before { content: "✓  "; font-weight: 800; }
.no li:before { content: "✕  "; font-weight: 800; }
.steps { display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 14px; margin-top: 8px; }
.step { background: #fff; border: 1px solid #E2E8EE; border-radius: 16px; padding: 16px; }
.step .n { width: 32px; height: 32px; border-radius: 50%; background: var(--teal); color: #fff; font-weight: 800;
  display: inline-flex; align-items: center; justify-content: center; }
.step b { display: block; font-family: 'Manrope', sans-serif; font-size: 17px; margin: 10px 0 4px 0; }
.step span { color: var(--muted); font-size: 14px; }
@media (max-width: 900px) { .steps { grid-template-columns: repeat(2, minmax(0,1fr)); } }
</style>
""", unsafe_allow_html=True)


def db():
    return pipeline.connect()


def review_days():
    with db() as con:
        return [d for (d,) in con.execute("SELECT day FROM review_days ORDER BY day DESC")]


def nice(day, fmt="%a %d %b %Y"):
    """A friendly date, e.g. 'Tue 6 Oct 2026' (no leading zero on the day)."""
    return re.sub(r"\b0(\d)", r"\1", datetime.fromisoformat(day).strftime(fmt))


def latest_run(day):
    with db() as con:
        r = con.execute("SELECT run_id, review_date, records_checked, operators_checked, seconds_taken, finished_at"
                        " FROM runs WHERE finished_at IS NOT NULL AND review_date=? ORDER BY run_id DESC LIMIT 1",
                        (day,)).fetchone()
    return None if r is None else dict(zip(["run_id", "review_date", "records", "operators", "secs", "finished"], r))


def decide(run_id, op, decision, reviewer):
    with db() as con:
        con.execute("INSERT INTO decisions (run_id, operator_code, decision, reviewer, ts) VALUES (?,?,?,?,?)",
                    (run_id, op, decision, reviewer, pipeline.now()))
        pipeline.audit(con, f"Reviewer decision: {decision}", f"{op} - by {reviewer}")


def decisions(run_id):
    with db() as con:
        rows = con.execute("SELECT operator_code, decision, reviewer, ts FROM decisions WHERE run_id=? ORDER BY id",
                           (run_id,)).fetchall()
    return {op: (d, who, ts) for op, d, who, ts in rows}


def hourly(op, day):
    """Activity by hour on the review day, next to the operator's average day."""
    with db() as con:
        q = """SELECT CAST(strftime('%H', ts) AS INT) AS hour, substr(ts,1,10) AS day FROM {t}
               WHERE operator_code=?"""
        rows = pd.concat([pd.read_sql_query(q.format(t=t), con, params=(op,))
                          for t in ("enrolments", "verifications", "detaches")])
    if rows.empty:
        return None
    days_worked = rows.loc[rows["day"] < day, "day"].nunique() or 1
    that_day = rows[rows["day"] == day].groupby("hour").size()
    usual = rows[rows["day"] < day].groupby("hour").size() / days_worked
    frame = pd.DataFrame({nice(day, "%a %d %b"): that_day, "Normal day": usual}).reindex(range(24)).fillna(0)
    frame.index = [f"{h:02d}:00" for h in frame.index]
    return frame


def level(risk):
    return ("high", "High risk") if risk >= 70 else ("med", "Medium risk") if risk >= 50 else ("low", "Low risk")


# ---------------- sidebar ----------------
with st.sidebar:
    st.markdown('<div class="brand"><small>CompuLynx AI Spark</small>🛡️ Fraud Detection Engine</div>',
                unsafe_allow_html=True)
    ai_ok = explainer.ollama_ready()
    st.markdown(f'<div class="status"><span class="dot" style="background:{"#3DDC97" if ai_ok else "#FF6B6B"}"></span>'
                f'Private AI {"online" if ai_ok else "offline"}</div>', unsafe_allow_html=True)
    st.divider()
    st.markdown('<div class="side-label">Day to check</div>', unsafe_allow_html=True)
    days = review_days()
    day = st.selectbox("Day to check", days, format_func=nice, key="day", label_visibility="collapsed")
    if pipeline.running():
        st.info("A check is running now.")
        if st.button("Refresh", width="stretch"):
            st.rerun()
    elif st.button(f"▶  Run check for {nice(day, '%a %d %b')}", type="primary", width="stretch"):
        bar = st.progress(0.0, text="Starting")
        try:
            pipeline.run(review_day=day, progress=lambda step, frac: bar.progress(min(frac, 1.0), text=step))
        except pipeline.AlreadyRunning as err:
            st.warning(str(err))
        else:
            st.rerun()
    st.caption("Runs automatically every night at 1:00 am.")
    st.divider()
    st.markdown('<div class="side-label">Reviewer</div>', unsafe_allow_html=True)
    reviewer = st.text_input("Reviewer", value="Branch Operations Reviewer", key="reviewer",
                             label_visibility="collapsed")
    st.caption("Demo data · coded IDs only")

run = latest_run(day)

st.markdown(f'<div class="hero"><div class="kicker">Review queue</div>'
            f'<h1>AI-Powered Early Fraud Detection Engine</h1>'
            f'<span class="date">📅 {nice(day, "%A %d %B %Y")}</span></div>', unsafe_allow_html=True)

tab_queue, tab_audit, tab_safety = st.tabs(["🚩 Cases to review", "🧾 Audit log", "🔒 What data it uses"])

with tab_queue:
    if run is None:
        st.info(f"Not checked yet. Press **Run check for {nice(day, '%a %d %b')}** in the sidebar.")
    else:
        with db() as con:
            queue = pd.read_sql_query("SELECT * FROM review_queue WHERE run_id=? ORDER BY rank", con,
                                      params=(run["run_id"],))
        done = decisions(run["run_id"])
        manual_hours = run["records"] * SECONDS_PER_RECORD / 3600
        st.markdown(f"""
<div class="kpis">
  <div class="kpi" style="--c:#0D7666"><div class="label">Records checked</div>
    <div class="value">{run['records']:,}</div><div class="sub">every record, not a sample</div></div>
  <div class="kpi" style="--c:#2F6FDB"><div class="label">Operators</div>
    <div class="value">{run['operators']}</div><div class="sub">each against their own normal</div></div>
  <div class="kpi" style="--c:#D9480F"><div class="label">Cases to review</div>
    <div class="value">{len(queue)}</div><div class="sub">out of {run['records']:,} records</div></div>
  <div class="kpi" style="--c:#5B4BDB"><div class="label">Time taken</div>
    <div class="value">{run['secs']:.0f}s</div>
    <div class="sub" title="Assumes {SECONDS_PER_RECORD} seconds per record">vs ~{manual_hours:.0f} staff-hours by hand*</div></div>
</div>""", unsafe_allow_html=True)
        reviewed = len(done)
        pct = 100 * reviewed / max(len(queue), 1)
        st.markdown(f'<div class="progress-row"><div class="txt">{reviewed} of {len(queue)} reviewed</div>'
                    f'<div class="track"><div class="fill" style="width:{pct:.0f}%"></div></div></div>',
                    unsafe_allow_html=True)

        for _, case in queue.iterrows():
            facts = json.loads(case["facts_json"])
            risk = int(case["risk"])
            lv, lv_word = level(risk)
            state = done.get(case["operator_code"])
            with st.container(key=f"case-{lv}-{case['rank']}"):
                left, right = st.columns([5, 1.35], vertical_alignment="center")
                with left:
                    st.markdown(
                        f'<div class="case-head" style="--c:var(--{lv})">'
                        f'<span class="rank">{case["rank"]}</span>'
                        f'<span class="op">{case["operator_code"]}</span>'
                        f'<span class="branch">{case["branch_code"]}</span>'
                        f'<span class="risk">{lv_word} · {risk}</span>'
                        f'<span class="meter"><div style="width:{risk}%"></div></span></div>'
                        f'<div class="sentence">{html.escape(case["sentence"])}</div>',
                        unsafe_allow_html=True)
                    chips = ('<span class="chip chip-ai">✨ AI-written · facts checked</span>'
                             if case["sentence_source"] == "ai" else
                             '<span class="chip chip-tpl">📋 Fact-based sentence</span>')
                    if state:
                        cls, icon = ("chip-inv", "🔍") if state[0] == "Investigate" else ("chip-ok", "✓")
                        chips += f'<span class="chip {cls}">{icon} {state[0]} · {state[2][11:16]}</span>'
                    st.markdown(chips, unsafe_allow_html=True)
                with right:
                    if not state:
                        if st.button("🔍 Investigate", key=f"inv{case['rank']}", type="primary", width="stretch"):
                            decide(run["run_id"], case["operator_code"], "Investigate", reviewer)
                            st.rerun()
                        if st.button("✓ Not a concern", key=f"ok{case['rank']}", width="stretch"):
                            decide(run["run_id"], case["operator_code"], "Not a concern", reviewer)
                            st.rerun()
                with st.expander("Show the numbers"):
                    a, b = st.columns([1, 1.3])
                    with a:
                        for s in facts["signals"]:
                            p = explainer.phrase(s)
                            st.markdown(f"- {p[0].upper() + p[1:]}")
                        if case["sentence_source"] != "ai" and case["draft"]:
                            reason = case["sentence_source"].replace("template (AI draft ", "").rstrip(")")
                            st.markdown(f'<div class="note"><b>AI draft rejected</b>: it {html.escape(reason)}.<br>'
                                        f'“{html.escape(case["draft"])}”</div>', unsafe_allow_html=True)
                    with b:
                        frame = hourly(case["operator_code"], run["review_date"])
                        if frame is not None:
                            st.bar_chart(frame, color=["#D9480F", "#A9BBC8"], height=230, stack=False)
            st.write("")
        st.caption(f"* Assumes {SECONDS_PER_RECORD} seconds to check one record by hand.")

with tab_audit:
    with db() as con:
        log = pd.read_sql_query("SELECT ts AS 'When', event AS 'Event', detail AS 'Detail'"
                                " FROM audit_log ORDER BY id DESC LIMIT 300", con)
    st.dataframe(log, width="stretch", hide_index=True, height=560,
                 column_config={"When": st.column_config.TextColumn(width="small"),
                                "Event": st.column_config.TextColumn(width="medium"),
                                "Detail": st.column_config.TextColumn(width="large")})

with tab_safety:
    st.markdown("### Looks at how work is done, never at who the customer is")
    a, b = st.columns(2)
    with a:
        st.markdown('<div class="panel yes"><h4>What it uses</h4><ul>'
                    '<li>Coded operator, branch and device IDs</li>'
                    '<li>Date and time of each activity</li>'
                    '<li>Fingerprint quality score (a number) and retries</li>'
                    '<li>Verification result: pass or fail</li>'
                    '<li>KYC documents complete: yes or no</li>'
                    '<li>Detach reason given: yes or no</li></ul></div>', unsafe_allow_html=True)
    with b:
        st.markdown('<div class="panel no"><h4>What it never uses</h4><ul>'
                    '<li>Fingerprint images or templates</li>'
                    '<li>Customer names, ID numbers, phones, addresses</li>'
                    '<li>Account numbers or card details</li>'
                    '<li>Photos or scanned ID documents</li></ul></div>', unsafe_allow_html=True)
    st.markdown("### How a case is decided")
    st.markdown('<div class="steps">'
                '<div class="step"><span class="n">1</span><b>Model spots it</b>'
                '<span>Compares each operator with their own past days.</span></div>'
                '<div class="step"><span class="n">2</span><b>Private AI explains</b>'
                '<span>Runs on this computer. Nothing goes to the internet.</span></div>'
                '<div class="step"><span class="n">3</span><b>Facts are checked</b>'
                '<span>A wrong or missing fact means the AI sentence is not used.</span></div>'
                '<div class="step"><span class="n">4</span><b>A person decides</b>'
                '<span>Nothing is blocked or acted on automatically.</span></div>'
                '</div>', unsafe_allow_html=True)
