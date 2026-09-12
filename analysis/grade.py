#!/usr/bin/env python3
"""
Grade representatives from the pulled data using the lexicons in topics.py.

Reads the cumulative master CSVs under DATA_DIR:
    data/<parliament>/questions/questions_master.csv
    data/<parliament>/plenary_business/plenary_business_master.csv
    data/<parliament>/votes_on_division/votes_on_division_master.csv
    data/<parliament>/members/members_master.csv          (roster join)

For every representative it produces:
  - topic stance from what they SAY (pro/con lexicon on questions + speeches),
  - topic stance from how they VOTE (division motion stance x their vote),
  - a general tone score (positive/negative language),
  - an activity/engagement count,
and writes two CSVs the app can read (joined to constituency/party):
    analysis/output/member_topic_scores.csv   (one row per member x topic)
    analysis/output/member_grades.csv         (one row per member)

Usage:
    python -m analysis.grade                 # grade everyone
    python -m analysis.grade --current-only  # only sitting members
    python -m analysis.grade --data-dir data --out analysis/output

The scoring is deliberately simple and transparent (word lists, no ML). Tune
analysis/topics.py to change what counts as pro/con for each category.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    pd = None

# Allow running as a script (python analysis/grade.py) or module.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analysis.topics import TOPICS, GENERAL_POSITIVE, GENERAL_NEGATIVE  # noqa: E402

# --- build fast lookup indices from the lexicons -----------------------------
_WORD_RE = re.compile(r"[a-z0-9']+")


def _norm_terms(terms):
    return [" ".join(_WORD_RE.findall(t.lower())) for t in terms if t.strip()]


# term -> {"kw": set(topics), "pro": set(topics), "con": set(topics), "tone": +1/-1}
INDEX: dict = defaultdict(lambda: {"kw": set(), "pro": set(), "con": set(), "tone": 0})
for _topic, _spec in TOPICS.items():
    for _t in _norm_terms(_spec.get("keywords", [])):
        INDEX[_t]["kw"].add(_topic)
    for _t in _norm_terms(_spec.get("pro", [])):
        INDEX[_t]["pro"].add(_topic)
    for _t in _norm_terms(_spec.get("con", [])):
        INDEX[_t]["con"].add(_topic)
for _t in _norm_terms(GENERAL_POSITIVE):
    INDEX[_t]["tone"] = 1
for _t in _norm_terms(GENERAL_NEGATIVE):
    INDEX[_t]["tone"] = -1

INDEX = dict(INDEX)
MAX_NGRAM = max((len(t.split()) for t in INDEX), default=1)


# Negation cues: a matched stance/tone term is flipped if one of these appears
# in the few tokens just before it ("not fund the NHS" -> con, not pro). This is
# a pre-term window only, so it can't catch post-modified attacks
# ("net zero is a disaster") — an inherent limit of lexicon scoring.
NEGATIONS = {"not", "no", "never", "without", "cannot", "can't", "don't", "dont",
             "doesn't", "doesnt", "isn't", "isnt", "aren't", "arent", "won't",
             "wont", "wasn't", "weren't", "nor", "neither", "hardly", "barely",
             "lacks", "lacking", "against", "oppose", "opposed", "reject"}
_NEG_WINDOW = 3


def score_text(text: str):
    """Return (topic_hits, tone_pos, tone_neg).

    Sequential longest-match scan (so "climate change" counts once, not also as
    "climate"), with pre-term negation flipping. Stance (pro/con) is only counted
    for a topic the statement is actually ABOUT — a topic must earn a keyword hit
    before its pro/con counts — so stance words shared across categories don't
    bleed onto unrelated topics.
    """
    tokens = _WORD_RE.findall(text.lower())
    n = len(tokens)
    mentions: dict = defaultdict(int)
    pro: dict = defaultdict(int)
    con: dict = defaultdict(int)
    tone_pos = tone_neg = 0
    i = 0
    while i < n:
        entry = None
        step = 1
        for L in range(min(MAX_NGRAM, n - i), 0, -1):  # longest match wins
            term = tokens[i] if L == 1 else " ".join(tokens[i:i + L])
            e = INDEX.get(term)
            if e:
                entry, step = e, L
                break
        if entry is None:
            i += 1
            continue
        neg = any(tokens[j] in NEGATIONS for j in range(max(0, i - _NEG_WINDOW), i))
        for tp in entry["kw"]:
            mentions[tp] += 1
        pro_side, con_side = (con, pro) if neg else (pro, con)
        for tp in entry["pro"]:
            pro_side[tp] += 1
        for tp in entry["con"]:
            con_side[tp] += 1
        if entry["tone"]:
            polarity = -entry["tone"] if neg else entry["tone"]
            if polarity > 0:
                tone_pos += 1
            else:
                tone_neg += 1
        i += step
    # A topic is "present" if a keyword OR a (distinctive) pro/con phrase fired.
    # Pro/con phrases are topic-specific, so this doesn't bleed across topics, and
    # it's needed because longest-match consumes keyword tokens inside a phrase
    # (e.g. "homes" inside "build more homes").
    topic_hits: dict = {}
    for tp in set(mentions) | set(pro) | set(con):
        topic_hits[tp] = {"mentions": mentions.get(tp, 0), "pro": pro.get(tp, 0),
                          "con": con.get(tp, 0)}
    return topic_hits, tone_pos, tone_neg


def motion_topic_stance(text: str):
    """For a division motion, return {topic: +1/-1/0} — the motion's own lean."""
    hits, _, _ = score_text(text)
    out = {}
    for tp, h in hits.items():
        if h["pro"] or h["con"] or h["mentions"]:
            out[tp] = (1 if h["pro"] > h["con"] else -1 if h["con"] > h["pro"] else 0)
    return out


_VOTED_PREFIX_RE = re.compile(r"^\s*voted\s+\w+\s+on:\s*", re.I)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


# --- per-member accumulator ---------------------------------------------------
def _blank_member():
    return {
        "name": "", "party": "", "constituency": "", "status": "", "parliament": "",
        "n_questions": 0, "n_speeches": 0, "n_votes": 0,
        "tone_pos": 0, "tone_neg": 0,
        # topic -> counts
        "topics": defaultdict(lambda: {"mentions": 0, "spoken_pro": 0, "spoken_con": 0,
                                       "vote_pro": 0, "vote_con": 0}),
    }


def load_roster(parl_dir: Path):
    """Return {member_id: info, "name::"+norm_name: info} from members_master.csv."""
    path = parl_dir / "members" / "members_master.csv"
    roster_by_id, roster_by_name = {}, {}
    if not path.exists():
        return roster_by_id, roster_by_name
    for chunk in pd.read_csv(path, dtype=str, keep_default_na=False,
                             encoding="utf-8-sig", chunksize=5000):
        for r in chunk.to_dict("records"):
            # Canonical key: the roster id where present, else the normalised
            # name. Records that carry an id and records that carry only a name
            # both resolve to this one key, so a member isn't double-counted.
            canon = r["id"] if r.get("id") else "nk:" + _norm_name(r.get("name", ""))
            info = {"name": r.get("name", ""), "party": r.get("party", ""),
                    "constituency": r.get("constituency", ""),
                    "status": r.get("status", ""), "key": canon}
            if r.get("id"):
                roster_by_id[r["id"]] = info
            if r.get("name"):
                roster_by_name[_norm_name(r["name"])] = info
    return roster_by_id, roster_by_name


def _norm_name(name: str) -> str:
    n = name.strip().lower()
    # NI stores "Surname, Forename" — normalise to a comparable token set
    if "," in n:
        surname, _, rest = n.partition(",")
        n = f"{rest.strip()} {surname.strip()}"
    n = re.sub(r"\b(mr|mrs|ms|miss|dr|sir|dame|rt|hon|the)\b", " ", n)
    return re.sub(r"[^a-z ]+", " ", n).strip()


# Chair/office and parsing-artifact "speakers" that aren't gradeable members.
# Only applied to speakers NOT matched to the roster, so a real member is never
# dropped even if their name happens to contain one of these words.
_CHAIR_MARKERS = ("speaker", "presiding officer", "llywydd", "lywydd", "chairman",
                  "chairperson", "the chair", "deputy chair", "lord speaker",
                  "clerk", "temporary chair")
_HAS_DIGIT = re.compile(r"\d")


def _is_gradeable_name(name: str) -> bool:
    """False for the chair and plenary parsing artifacts ("13:3", "level 1")."""
    n = (name or "").strip().lower()
    if not n or _HAS_DIGIT.search(n):
        return False
    if any(marker in n for marker in _CHAIR_MARKERS):
        return False
    return len(re.sub(r"[^a-z]", "", n)) >= 2


def grade(data_dir: Path, out_dir: Path, current_only: bool = False):
    if pd is None:
        sys.exit("pandas is required: pip install pandas")
    members: dict = defaultdict(_blank_member)

    parl_dirs = sorted([p for p in data_dir.iterdir() if p.is_dir()]) if data_dir.exists() else []
    if not parl_dirs:
        sys.exit(f"No parliament folders under {data_dir}/ — run the scraper first.")

    for parl_dir in parl_dirs:
        parl_slug = parl_dir.name
        roster_by_id, roster_by_name = load_roster(parl_dir)

        def resolve(rec):
            mid = (rec.get("member_id") or "").strip()
            info = roster_by_id.get(mid)
            if info is None:
                info = roster_by_name.get(_norm_name(rec.get("member_name", "")))
            if info is None and not _is_gradeable_name(rec.get("member_name", "")):
                return None  # chair / parsing artifact, not a member — skip
            if info is not None:
                # Canonicalise to the roster identity so id-only and name-only
                # records for the same person merge into one member.
                key = f"{parl_slug}:{info['key']}"
            else:
                nm = _norm_name(rec.get("member_name", ""))
                key = f"{parl_slug}:name:{nm}" if nm else f"{parl_slug}:unknown"
            m = members[key]
            if not m["name"]:
                m["name"] = (info or {}).get("name") or rec.get("member_name", "")
                m["party"] = (info or {}).get("party") or rec.get("member_party", "")
                m["constituency"] = (info or {}).get("constituency") or rec.get("member_constituency", "")
                m["status"] = (info or {}).get("status", "")
                m["parliament"] = rec.get("parliament", parl_slug)
            return m

        # ---- spoken: questions + plenary ----
        for dtype, counter in (("questions", "n_questions"),
                               ("plenary_business", "n_speeches")):
            path = parl_dir / dtype / f"{dtype}_master.csv"
            if not path.exists():
                continue
            for chunk in pd.read_csv(path, dtype=str, keep_default_na=False,
                                     encoding="utf-8-sig", chunksize=20000):
                for rec in chunk.to_dict("records"):
                    text = rec.get("text", "") or ""
                    if not text:
                        continue
                    m = resolve(rec)
                    if m is None:
                        continue  # chair / artifact speaker
                    m[counter] += 1
                    hits, tpos, tneg = score_text(text)
                    m["tone_pos"] += tpos
                    m["tone_neg"] += tneg
                    for tp, h in hits.items():
                        agg = m["topics"][tp]
                        agg["mentions"] += h["mentions"]
                        agg["spoken_pro"] += h["pro"]
                        agg["spoken_con"] += h["con"]

        # ---- voting ----
        path = parl_dir / "votes_on_division" / "votes_on_division_master.csv"
        if path.exists():
            for chunk in pd.read_csv(path, dtype=str, keep_default_na=False,
                                     encoding="utf-8-sig", chunksize=20000):
                for rec in chunk.to_dict("records"):
                    direction = (rec.get("metadata_vote_direction", "") or "").lower()
                    if direction not in ("aye", "no"):
                        continue  # abstain / no_vote / unknown carry no stance
                    motion = rec.get("title", "") or _VOTED_PREFIX_RE.sub("", rec.get("text", "") or "")
                    if not motion:
                        continue
                    m = resolve(rec)
                    if m is None:
                        continue  # chair / artifact speaker
                    m["n_votes"] += 1
                    support = 1 if direction == "aye" else -1
                    for tp, lean in motion_topic_stance(motion).items():
                        if lean == 0:
                            continue
                        aligned = lean * support  # +1 member pro-topic, -1 con
                        if aligned > 0:
                            m["topics"][tp]["vote_pro"] += 1
                        else:
                            m["topics"][tp]["vote_con"] += 1

    _write_outputs(members, out_dir, current_only)


# Stance scoring configuration.
STANCE_SHRINK_K = 4    # pseudo-count: shrinks thin evidence toward 0 (1 hit != +-1)
MIN_STANCE_HITS = 3    # min pro+con hits for a topic to qualify as top_pro/top_con
VOTE_WEIGHT = 2.0      # votes weigh more than speech (unambiguous, negation-proof)
SPEECH_WEIGHT = 1.0


def _stance(pro: int, con: int):
    """Shrunk stance in [-1, 1]: (pro - con) / (pro + con + K).

    The +K pseudo-count pulls thin evidence toward 0, so a single hit gives a
    small score rather than saturating at +-1; only strong, consistent evidence
    approaches the extremes.
    """
    total = pro + con
    return round((pro - con) / (total + STANCE_SHRINK_K), 3) if total else 0.0


def _write_outputs(members: dict, out_dir: Path, current_only: bool):
    out_dir.mkdir(parents=True, exist_ok=True)
    topic_path = out_dir / "member_topic_scores.csv"
    grade_path = out_dir / "member_grades.csv"

    n_members = 0
    with open(topic_path, "w", newline="", encoding="utf-8-sig") as tf, \
         open(grade_path, "w", newline="", encoding="utf-8-sig") as gf:
        tw = csv.writer(tf)
        tw.writerow(["parliament", "member", "party", "constituency", "status", "topic",
                     "mentions", "spoken_pro", "spoken_con", "spoken_stance",
                     "vote_pro", "vote_con", "vote_stance", "combined_stance"])
        gw = csv.writer(gf)
        gw.writerow(["parliament", "member", "party", "constituency", "status",
                     "n_questions", "n_speeches", "n_votes", "activity_total",
                     "tone_score", "topics_engaged", "top_pro_topic", "top_con_topic"])

        for m in members.values():
            if current_only and m["status"] and m["status"] != "current":
                continue
            if not m["name"]:
                continue
            n_members += 1
            topic_stances = {}
            topic_evidence = {}
            for tp, h in sorted(m["topics"].items()):
                sp_n = h["spoken_pro"] + h["spoken_con"]
                vt_n = h["vote_pro"] + h["vote_con"]
                sp = _stance(h["spoken_pro"], h["spoken_con"])
                vt = _stance(h["vote_pro"], h["vote_con"])
                # combined: weighted average of the signals present (votes count more)
                num = den = 0.0
                if sp_n:
                    num += SPEECH_WEIGHT * sp
                    den += SPEECH_WEIGHT
                if vt_n:
                    num += VOTE_WEIGHT * vt
                    den += VOTE_WEIGHT
                combined = round(num / den, 3) if den else 0.0
                topic_stances[tp] = combined
                topic_evidence[tp] = sp_n + vt_n
                # only emit rows where the member actually engaged the topic
                if h["mentions"] or sp_n or vt_n:
                    tw.writerow([m["parliament"], m["name"], m["party"], m["constituency"],
                                 m["status"], tp, h["mentions"], h["spoken_pro"],
                                 h["spoken_con"], sp, h["vote_pro"], h["vote_con"], vt, combined])

            tone = _stance(m["tone_pos"], m["tone_neg"])
            activity = m["n_questions"] + m["n_speeches"] + m["n_votes"]
            engaged = {t: s for t, s in topic_stances.items() if s != 0}
            # top pro/con only from well-evidenced topics, so a 1-hit blip can't win
            confident = {t: s for t, s in engaged.items()
                         if topic_evidence.get(t, 0) >= MIN_STANCE_HITS}
            top_pro = max(confident.items(), key=lambda kv: kv[1], default=("", 0))
            top_con = min(confident.items(), key=lambda kv: kv[1], default=("", 0))
            gw.writerow([m["parliament"], m["name"], m["party"], m["constituency"], m["status"],
                         m["n_questions"], m["n_speeches"], m["n_votes"], activity,
                         tone, len(engaged),
                         top_pro[0] if top_pro[1] > 0 else "",
                         top_con[0] if top_con[1] < 0 else ""])

    print(f"Graded {n_members} representatives"
          f"{' (current only)' if current_only else ''}.")
    print(f"  per-topic scores -> {topic_path}")
    print(f"  per-member grades -> {grade_path}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Grade representatives from pulled data.")
    ap.add_argument("--data-dir", default="data", help="root of the pulled data (default: data)")
    ap.add_argument("--out", default="analysis/output", help="output directory")
    ap.add_argument("--current-only", action="store_true",
                    help="only grade sitting members (status=current)")
    args = ap.parse_args(argv)
    grade(Path(args.data_dir), Path(args.out), current_only=args.current_only)


if __name__ == "__main__":
    main()
