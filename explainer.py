"""Turn a case's checked facts into one plain-English sentence.

The language model (Ollama, running locally) only rewords the facts. Every number in its sentence is
checked against the facts; if anything does not match, a fixed template sentence is used instead.
"""
import re

import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama3.2:3b"
NUM = re.compile(r"\d+(?:[.:]\d+)?")
FORBIDDEN = re.compile(r"\b(fraud\w*|stole|steal\w*|theft|criminal|guilty|illegal|significant\w*|"
                       r"dramatic\w*|alarming\w*|suspicious\w*)\b", re.I)
ROLE_WORDS = re.compile(r"\b(should|must|recommend\w*|investigat\w*|review\w*)\b", re.I)


def phrase(s):
    """One fact, as a plain phrase that starts with a verb."""
    k = s["key"]
    if k == "enrol_count_at_night":
        times = f", {s['times']} times their normal daily volume" if s.get("times", 0) >= 2 else ""
        return (f"enrolled {s['today']} customers between {s['start']} and {s['end']}, outside working hours, "
                f"against a normal {s['normal']} a day{times}")
    if k == "enrol_count":
        times = f", {s['times']} times their normal daily volume" if s.get("times", 0) >= 2 else ""
        return f"enrolled {s['today']} customers against a normal {s['normal']} a day{times}"
    if k == "enrol_off_hours":
        return f"did {s['today']} enrolments outside working hours, between {s['start']} and {s['end']}"
    if k == "verif_off_hours":
        return f"ran {s['today']} fingerprint verifications outside working hours, between {s['start']} and {s['end']}"
    if k == "quality_sameness":
        return (f"recorded almost identical fingerprint quality scores, all between {s['low']} and {s['high']}, "
                f"across {s['today']} captures")
    if k == "avg_retries":
        return f"needed {s['today']} capture retries per enrolment on average, against a normal {s['normal']}"
    if k == "kyc_incomplete":
        return f"completed {s['today']} of {s['of']} enrolments with incomplete KYC documents"
    if k == "foreign_device":
        return (f"did {s['today']} enrolments on device {s['device']}, which belongs to branch "
                f"{s['device_branch']}")
    if k == "verif_fail_rate":
        return (f"had {s['today']} of {s['of']} fingerprint verifications fail, against a normal failure rate "
                f"of {s['normal_pct']}%")
    if k == "detach_count":
        usual = "none" if s["normal_month"] == 0 else f"about {s['normal_month']}"
        noun = "customer" if s["today"] == 1 else "customers"
        return f"detached fingerprints for {s['today']} {noun} in one day, when they normally do {usual} in a month"
    if k == "detach_no_reason":
        return f"gave no reason for {s['today']} fingerprint detaches"
    raise ValueError(k)


def merged_signals(facts):
    """Fold 'outside working hours' into the volume fact when both describe the same enrolments."""
    sig = {s["key"]: s for s in facts["signals"]}
    if "enrol_count" in sig and "enrol_off_hours" in sig:
        c, o = sig["enrol_count"], sig["enrol_off_hours"]
        merged = dict(c, key="enrol_count_at_night", start=o["start"], end=o["end"])
        return [merged if s is c else s for s in facts["signals"] if s is not o]
    return facts["signals"]


def template(facts):
    parts = [phrase(s) for s in merged_signals(facts)]
    if not parts:
        return f"{facts['operator']} showed activity that was slightly different from their normal pattern."
    body = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + ", and " + parts[-1]
    return f"{facts['operator']} {body}."


def prompt(facts):
    t = template(facts)
    return (
        "The sentence below describes what one bank staff member did yesterday. Make it read more smoothly "
        "for a bank manager, changing as few words as possible.\n"
        f"Rules: start with \"{facts['operator']} {t.split()[1]}\". Keep it one sentence. Keep every number exactly "
        "as written, with the same words on each side of it. Do not add, remove or change any fact, and do not "
        "add opinions such as 'significantly'. Do not accuse anyone. Output only the sentence.\n\n"
        "Example\n"
        "Sentence: OP_003 needed 4.1 capture retries per enrolment on average, against a normal 0.7, and had "
        "9 of 40 fingerprint verifications fail, against a normal failure rate of 4%.\n"
        "Smoother: OP_003 needed 4.1 capture retries per enrolment on average, against a normal 0.7, and "
        "9 of 40 fingerprint verifications failed, against a normal failure rate of 4%.\n\n"
        f"Sentence: {t}\n"
        "Smoother:"
    )


def number_contexts(text):
    """Each number with the words either side of it, e.g. ('normal', '7', 'a')."""
    text = re.sub(r"\b[A-Z]{2}_\d+\b", "code", text)      # OP_017, BR_02, DV_0209 are names, not facts
    words = re.findall(r"\d+(?:[.:]\d+)?%?|[a-z]+", text.lower())
    at = lambda i: words[i] if 0 <= i < len(words) else ""
    return [(at(i - 1), w, at(i + 1)) for i, w in enumerate(words) if w[0].isdigit()]


def check(sentence, facts):
    """Return a reason the sentence fails, or None if every fact checks out."""
    allowed = set(NUM.findall(template(facts))) | set(NUM.findall(facts["operator"] + " " + facts["branch"]))
    if not sentence.startswith(facts["operator"]):
        return f"does not start with {facts['operator']}"
    if FORBIDDEN.search(sentence):
        return "uses accusing language"
    bad = [n for n in NUM.findall(sentence) if n not in allowed]
    if bad:
        return f"contains numbers not in the facts: {', '.join(bad)}"
    first_verb = template(facts).split()[1]
    if not sentence.startswith(f"{facts['operator']} {first_verb}") or ROLE_WORDS.search(sentence):
        return "changed who did what"
    got = number_contexts(sentence)
    missing = [" ".join(c) for c in number_contexts(template(facts)) if c not in got]
    if missing:
        return f"changed or dropped the fact “{missing[0]}”"
    if len(sentence.split()) > 55 or re.search(r"[.!?]\s+\S", sentence.rstrip(".")):
        return "is longer than one sentence"
    return None


def explain(facts):
    """Returns (sentence, source, draft). source is 'ai', 'template' or 'template (AI offline)'."""
    if not facts["signals"]:
        return template(facts), "template", None
    try:
        r = requests.post(OLLAMA_URL, json={"model": MODEL, "prompt": prompt(facts), "stream": False,
                                            "options": {"temperature": 0.1, "num_predict": 90}}, timeout=90)
        r.raise_for_status()
        draft = r.json()["response"].strip().strip('"').strip()
    except requests.RequestException:
        return template(facts), "template (AI offline)", None
    problem = check(draft, facts)
    if problem:
        return template(facts), f"template (AI draft {problem})", draft
    return draft, "ai", draft


def ollama_ready():
    try:
        tags = requests.get("http://localhost:11434/api/tags", timeout=3).json()
        return any(m["name"].startswith(MODEL) for m in tags.get("models", []))
    except requests.RequestException:
        return False
