# AI-Powered Early Fraud Detection Engine (demo)

An MVP for the CompuLynx AI Spark Hackathon, 7 October 2026 (Alfred Ochola and Caleb Rubalema).

It reviews one day of COMPAS-style activity: fingerprint enrolments, verifications and detaches. It finds the operators whose activity looks least like their own normal, and shows a short review queue with a plain-English reason for each case. You pick the day to check in the portal. It uses a mock database only. It does not connect to, or change, the NCBA COMPAS application.

## Run it

| When | Do this |
|---|---|
| First time on a computer | Double-click `setup.bat`. It installs the libraries, downloads the AI model and builds the demo data. |
| Before each demo | Double-click `reset_demo.bat`. You get fresh data, all three demo days checked, and no cases reviewed yet. It takes 2 to 3 minutes. |
| To show the portal | Double-click `start_demo.bat`. The portal opens in the browser at http://localhost:8501. Keep the black window open, minimised. |

Ollama must be running (it starts with Windows after installation). The sidebar shows a green dot when the private AI is ready. If it isn't running, the portal still works and uses fact-based sentences.

To check one day from the command line: `python pipeline.py 2026-10-05`.

## What is in the folder

| File | What it does |
|---|---|
| `seed_demo_db.py` | Builds `demo.db`. It holds 30 days of mock activity (7 Sep to 6 Oct 2026) for 96 coded operators at 12 branches, with cases planted on three demo days. |
| `detector.py` | The anomaly model. It compares each operator's day with their own earlier days, using scikit-learn's Isolation Forest, and ranks the most unusual cases. When it checks a past date, it never looks at data after that date. |
| `explainer.py` | Writes the sentence. The private AI (Ollama, `llama3.2:3b`) rewords the facts. A fact check rejects any sentence that changes a number, drops a fact or changes who did what, and a fact-based sentence is used instead. |
| `pipeline.py` | The check for one day: detect, then explain, then save the queue and write to the audit log. |
| `app.py` | The review portal (Streamlit), with the day picker. |

## The three demo days

The days are the last three working days before the demo. Branches work a half day on Saturday and are closed on Sunday, so 3 and 4 Oct are not demo days.

| Day | Story | Planted cases |
|---|---|---|
| **Fri 2 Oct** | A quiet day | **OP_076**: 8 of 12 enrolments with incomplete KYC, and about 5 capture retries each. **OP_009**: 12 captures with quality scores of 77 to 78, which looks copied. |
| **Mon 5 Oct** | A normal day | **OP_058**: 5 fingerprint detaches at lunchtime, none with a reason. **OP_090**: 18 enrolments between 22:40 and 23:15. **OP_036**: 7 enrolments on a device from branch BR_07. **OP_022**: 19 of 45 verifications failed. |
| **Tue 6 Oct** | A busy day | **OP_017**: 40 enrolments between 01:50 and 02:30, with almost identical quality scores (normally 7 a day, 9am to 4pm). **OP_014**: 11 of 18 enrolments with incomplete KYC and 5 or more retries each. **OP_063**: 6 detaches in 20 minutes, 4 with no reason. **OP_032**: 30 verifications at about 11pm, most of them failed. **OP_081**: 14 enrolments with quality scores of 84 to 85. **OP_045**: 9 enrolments on a device from branch BR_02. |

Every planted case ranks at the top of its own day. Friday also shows two lower-risk cases, OP_049 and OP_023, which simply had a busy day. They are not planted, and they are the ones to mark "Not a concern".

## Five-minute demo script

1. **The problem (30 s).** "Every day, about 90 operators create around 2,500 records. Nobody can check them all, so problems are found weeks later."
2. **Pick a day and run the check (1 min).** In the sidebar, choose **Tue 6 Oct 2026** and press **Run check for Tue 6 Oct**. The progress bar reads the activity, learns each operator's normal and writes the explanations. Say: "This normally runs on its own at 1am for the day before."
3. **The queue (1.5 min).** Open case #1, OP_017. Read the sentence aloud. Open **See the numbers behind this case** and point to the chart: activity at 2am, when this operator normally works 9 to 4.
4. **Another day (45 s).** Switch to **Fri 2 Oct 2026**. "On a quiet day it flags only a handful of cases." Click **Investigate** on OP_076, then **Not a concern** on OP_049: "just a busy day. The system never accuses or blocks anyone. A person decides."
5. **Trust (45 s).** Open **Audit log**: every check, flag and decision has a date and time. Open **What data it uses**: no names, no fingerprint images, no internet. If any case shows "Fact-based sentence", open it. It shows the AI draft that the fact check rejected, and why.
6. **Close (30 s).** "It does not replace your fraud team. It tells them which few records, out of thousands, to check first, and why."

## Honest limits (say these if asked)

- The data is mock data, and the cases are planted. The demo proves the system works end to end. It does not prove how many real frauds it would catch; that needs a pilot on real data.
- COMPAS stores who enrolled, when, at which branch, approvals, rejections and detaches today. It does not yet store quality scores, capture retries or device codes for each record, so a real rollout needs COMPAS or the middleware to log them.
- The manual-review estimate assumes 30 seconds per record. Replace it with the bank's real daily volume and review time.
- The anomaly model will raise some false alarms. That is why a person always decides.
