#!/usr/bin/env python3
"""
Questions for the Scottish Parliament, the Senedd and the Northern Ireland
Assembly, built from their own votes.

The main quiz rests on mySociety's policy groupings, and those exist for the
House of Commons only. So an MSP, MS or MLA has a full voting record but no
position on any quiz statement, and cannot be matched. This module gives each
devolved legislature its own questions, in the only way that needs no one's
interpretation: every question is ONE division, a motion or a bill the
legislature actually voted on.

    "How would you have voted?"        you:    +1 for ... -1 against
                                       member: +1 aye, -1 no, 0 abstained,
                                               None if absent or not a member

What we decide, and what we do not:

  * Wording is not ours. A question shows the legislature's own title and the
    motion as it was put, word for word. Nothing is paraphrased.
  * Which way a vote counts is not ours. Aye is for, No is against.
  * Selection is a rule, not a choice of subjects (see `qualifies`):
      - votes on a whole motion, or on a bill at a stage that decides the bill
        as a whole. Amendments, single clauses and procedural business are
        left out: an amendment cannot be understood without the thing it
        amends, and procedure is not a view on anything;
      - where the house really divided: at least MIN_MINORITY of those voting
        were on the losing side. A vote everyone agreed on tells you nothing
        about which member is closer to you;
      - one question per title: a bill voted on at several stages is asked
        about once, at its most recent stage, which is the one that decided it;
      - the most recent MAX_QUESTIONS of those from the current term. Only
        when a new term has not yet produced MIN_FROM_TERM of them does the
        list reach back into the previous term, newest first. A member who
        was not sitting then simply has no position on those.

A single vote is weaker evidence than the Commons statements, which pool
several votes each, and members sometimes vote against a motion they
sympathise with because of its wording or its author. The apps say so.

Usage:
    python -m analysis.devolved                 # prints what would be asked
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from pathlib import Path

from analysis import mysociety

MAX_QUESTIONS = 30
MIN_FROM_TERM = 20
MIN_MINORITY = 0.10
NI_API = "https://data.niassembly.gov.uk"
# The Assembly's own page for one item of plenary business, vote included.
NI_PAGE = "https://aims.niassembly.gov.uk/plenary/details.aspx?&ses=0&doc={}&pn=0&sid=vd"

FOR, AGAINST, ABSTAIN, ABSENT, NOT_MEMBER = "f", "a", "b", "x", "."

# Business that decides how the house works rather than what it thinks.
PROCEDURAL = re.compile(
    r"business motion|business programme|closure of debate|extension of |suspen[ds]|"
    r"standing order|committee membership|membership of |appointment of |election of |"
    r"timetabl|sitting days|adjourn|that the (?:parliament|senedd|assembly) (?:do )?(?:now )?"
    r"(?:meet|sit|adjourn)|order of consideration|accelerated passage|"
    r"programme of business|business committee|financial resolution|money resolution",
    re.I)
# A numbered amendment, or one part of a bill. ("Motion without amendment" is
# the Senedd's phrase for a vote on the motion itself, so the bare word is not
# enough.)
AMENDMENT = re.compile(r"\bamendments?\s+\d|\bgwelliant\s+\d|motion amendment|"
                       r"^\s*amendment\b|\bclause \d|\bschedule \d|\blong title\b|"
                       r"\bsection \d|\bgroup \d", re.I)


def _clean(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def qualifies(title: str, kind: str, ayes: int, noes: int) -> bool:
    """The selection rule. `title` is the legislature's own title for the vote;
    `kind` is its own, or mySociety's, label for what sort of business it was."""
    if "amendment" in kind.lower() or AMENDMENT.search(title):
        return False
    if PROCEDURAL.search(f"{kind} {title}"):
        return False
    cast = ayes + noes
    if cast == 0:
        return False
    return min(ayes, noes) / cast >= MIN_MINORITY


def vote_code(vote: str) -> str:
    v = (vote or "").strip().lower()
    if v in ("aye", "yes", "for", "tellaye"):
        return FOR
    if v in ("no", "against", "tellno"):
        return AGAINST
    if v.startswith("abst"):
        return ABSTAIN
    return ABSENT


POSITION = {FOR: 1, AGAINST: -1, ABSTAIN: 0}


# --------------------------------------------------------------------------
# Scotland and Wales: divisions and votes are mySociety's; the motion itself
# is on each division's own page there.
# --------------------------------------------------------------------------
def _division_page(cache_dir: Path, chamber: str, key: str, day: str, number: int,
                   offline: bool) -> dict:
    """The division's page on TheyWorkForYou Votes, cached."""
    path = cache_dir / "divisions" / f"{key}.json"
    if not path.exists():
        if offline:
            return {}
        # division_votes() fetches and stores the same file
        mysociety.division_votes(cache_dir, key, chamber, day, number)
        time.sleep(0.25)                      # be a polite guest
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _motion_wording(text: str) -> str:
    """The motion itself, out of the announcement of its result.

    The Scottish Official Report records "The result of the division on motion
    S7M-1, in the name of X, on Y, is: For 60, Against 50... That the
    Parliament believes...". What members voted on starts at "That the".
    """
    text = _clean(text)
    m = re.search(r"\bThat the (?:Parliament|Senedd)\b", text)
    return text[m.start():] if m else ""


def _senedd_title(name: str) -> str:
    """'Item 6. Reform UK Debate - mobile phones. Motion without amendment.'"""
    name = re.sub(r"^\s*(?:Item|Eitem)\s+\d+\.\s*", "", _clean(name))
    name = re.sub(r"\.?\s*(Motion without amendment|Motion as amended|"
                  r"Cynnig heb ei ddiwygio|Cynnig wedi[’']i ddiwygio)\.?\s*$", "", name, flags=re.I)
    return name.rstrip(". ")


def from_mysociety(cache_dir: Path, chamber: str, term_start: str, earliest: str,
                   offline: bool = False) -> list:
    """Questions for Scotland or the Senedd, newest first.

    Every qualifying vote of the current term, up to MAX_QUESTIONS; if a young
    term has fewer than MIN_FROM_TERM, the previous one (back to `earliest`)
    makes up the difference.
    """
    divisions = mysociety.load_table(cache_dir, "divisions")
    d = divisions[(divisions["chamber_slug"] == chamber)
                  & (divisions["date"].astype(str) >= earliest)]
    out, seen = [], set()
    for row in d.sort_values(["date", "division_number"], ascending=False).itertuples():
        day, number = str(row.date), int(row.division_number)
        if len(out) >= MAX_QUESTIONS or (day < term_start and len(out) >= MIN_FROM_TERM):
            break
        page = _division_page(cache_dir, chamber, row.key, day, number, offline)
        if not page:
            continue
        motion = page.get("motion") or {}
        counts = (page.get("overall_breakdowns") or [{}])[0]
        ayes, noes = int(counts.get("for_motion") or 0), int(counts.get("against_motion") or 0)
        name = _clean(row.division_name)
        kind = str(motion.get("motion_type") or "")
        as_amended = bool(re.search(r"as amended|wedi[’']i ddiwygio", f"{name} {motion.get('text', '')}", re.I))
        if chamber == "senedd":
            title = _senedd_title(name)
            # The Senedd's record names the debate, not the motion's wording.
            # Once amended, the title no longer says what was voted on.
            if as_amended:
                continue
        else:
            title = _clean(motion.get("title") or "")
        # Scotland's record calls every vote "Decision Time"; the Senedd's has
        # the substance in the name of the vote.
        if not title or not qualifies(name if chamber == "senedd" else f"{name}: {title}",
                                      kind, ayes, noes):
            continue
        if title.lower() in seen:           # an earlier stage of something already asked
            continue
        seen.add(title.lower())
        out.append({
            "key": row.key,
            "date": day,
            "number": number,
            "title": title,
            "detail": _motion_wording(motion.get("text") or ""),
            "asAmended": as_amended,
            "ayes": ayes,
            "noes": noes,
            "link": f"{mysociety.VOTES_BASE}/decisions/division/{chamber}/{day}/{number}",
        })
    return out


# --------------------------------------------------------------------------
# Northern Ireland: divisions and votes are from the Assembly's own open data
# (collected by scrapers/ni_assembly.py); the motion text is fetched here.
# --------------------------------------------------------------------------
def _ni_plenary(cache_dir: Path, document_id: str, offline: bool) -> dict:
    path = cache_dir / "ni_plenary" / f"{document_id}.json"
    if not path.exists():
        if offline:
            return {}
        import requests
        try:
            r = requests.get(f"{NI_API}/plenary.asmx/GetPlenaryDetails_JSON",
                             params={"documentId": document_id}, timeout=60,
                             headers={"User-Agent": mysociety.USER_AGENT})
            r.raise_for_status()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(r.text, encoding="utf-8")
            time.sleep(0.25)
        except Exception as e:  # network or HTTP
            print(f"  ! could not fetch Assembly item {document_id} ({e})", file=sys.stderr)
            return {}
    try:
        item = json.loads(path.read_text(encoding="utf-8"))["PlenaryList"]["Plenary"]
        return item[0] if isinstance(item, list) else item
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return {}


def _ni_title(title: str) -> str:
    """'Second Stage: Flags Bill (NIA Bill 44/22-27) [Ms Paula Bradshaw]'"""
    title = re.sub(r"\s*\[[^\]]*\]?\s*$", "", _clean(title))      # who moved it
    title = re.sub(r"\s*\(NIA(?: Bill)? [^)]*\)", "", title)         # its number
    return title.strip(" -")


def from_ni_scrape(votes_csv: Path, cache_dir: Path, term_start: str,
                   offline: bool = False):
    """(candidate questions newest first, {division id: [(name, code)]})."""
    import pandas as pd

    if not votes_csv.exists():
        return [], {}
    df = pd.read_csv(votes_csv, low_memory=False, dtype=str).fillna("")
    df = df[df["date"].str[:10] >= term_start]
    ballots, questions = {}, []
    for division_id, g in df.groupby("metadata_division_id"):
        codes = [(n, vote_code(v)) for n, v in zip(g["member_name"], g["metadata_vote_direction"])]
        ballots[division_id] = codes
        ayes = sum(c == FOR for _, c in codes)
        noes = sum(c == AGAINST for _, c in codes)
        raw_title = g["title"].iloc[0]
        # The scrape keys votes by the division's event number. The motion is
        # filed under the Assembly's document number, which the scrape kept
        # inside the address of the result it read.
        found = re.search(r"documentId=(\d+)", g["metadata_division_result"].iloc[0])
        document = found.group(1) if found else ""
        item = _ni_plenary(cache_dir, document, offline) if document else {}
        kind = f"{item.get('DocumentType', '')} {item.get('MotionCategory', '')}"
        title = _ni_title(raw_title)
        if not title or not qualifies(raw_title, kind, ayes, noes):
            continue
        # A bill is only asked about at the stages that decide it as a whole.
        if re.search(r"\bbill\b", raw_title, re.I) and not re.match(
                r"\s*(second|final) stage\b", raw_title, re.I):
            continue
        text = _clean(item.get("Text") or "")
        questions.append({
            "key": f"ni-{division_id}",
            "date": g["date"].iloc[0][:10],
            "number": int(division_id),
            "title": title,
            "detail": "" if _ni_title(text) == title else text,
            "asAmended": False,
            "ayes": ayes,
            "noes": noes,
            "link": NI_PAGE.format(document) if document else "",
            "_division": division_id,
        })
    questions.sort(key=lambda q: (q["date"], q["key"]), reverse=True)
    kept, seen = [], set()
    for q in questions:
        subject = re.sub(r"^(second|final) stage:\s*", "", q["title"], flags=re.I).lower()
        if subject not in seen:
            seen.add(subject)
            kept.append(q)
    return kept[:MAX_QUESTIONS], ballots


# --------------------------------------------------------------------------
# Turning questions and votes into one quiz per legislature
# --------------------------------------------------------------------------
# Each legislature's questions get ids in a range of their own, so that an
# answer saved against one can never be read as an answer to another.
ID_BASE = {"scotland": 1_000_000_000_000, "senedd": 2_000_000_000_000, "ni": 3_000_000_000_000}


def statement_id(chamber: str, q: dict) -> int:
    if chamber == "ni":
        return ID_BASE[chamber] + int(q["number"])
    return ID_BASE[chamber] + int(q["date"].replace("-", "")) * 10_000 + int(q["number"])


def statement_text(q: dict) -> str:
    """What follows "I would have voted for…". A formula, not a summary."""
    title = q["title"]
    stage = re.match(r"(Second|Final) Stage:\s*(.+)$", title, re.I)
    if stage:
        return f"the {stage.group(2)} at its {stage.group(1).title()} Stage"
    return f"the motion “{title}”" + (" as amended" if q.get("asAmended") else "")


def _statement(chamber: str, q: dict) -> dict:
    is_bill = bool(re.search(r"\bBill\b", q["title"]))
    return {
        "id": statement_id(chamber, q),
        "name": q["title"],
        "text": statement_text(q),
        "detail": q["detail"],
        "link": q["link"],
        "group": "Bill" if is_bill else "Motion",
        "freeVote": False,
        "econ": 0,
        "social": 0,
        "termVotes": 1,
        "result": [q["ayes"], q["noes"]],
        "divisions": [{
            "key": q["key"],
            "date": q["date"],
            "number": q["number"],
            "title": q["title"],
            "alignment": "agree",
            "url": q["link"],
        }],
    }


def _member(m: dict, codes: list) -> dict:
    return {
        "id": m["person_id"],
        "name": m["name"],
        "party": m["party"],
        "area": m["area"],
        "pos": [POSITION.get(c) for c in codes],
        "votes": codes,
    }


def build_set(chamber: str, questions: list, members: list, cast, sat_on) -> dict:
    """One legislature's quiz.

    `cast(question)` gives {person id: vote code} for those who voted;
    `sat_on(person id, day)` says whether someone was a member that day, which
    is what separates "absent" from "not there to vote".
    """
    statements = [_statement(chamber, q) for q in questions]
    votes = [cast(q) for q in questions]
    out_members = []
    for m in members:
        pid = m["person_id"]
        codes = []
        for q, ballot in zip(questions, votes):
            code = ballot.get(pid)
            if code is None:
                code = ABSENT if sat_on(pid, q["date"]) else NOT_MEMBER
            codes.append(code)
        out_members.append(_member(m, codes))
    return {"statements": statements, "members": out_members}


def build(cache_dir: Path, data_dir: Path, people=None, fetch: bool = True) -> dict:
    """{parliament name: quiz} for every devolved legislature we hold votes for."""
    people = people or mysociety.People(cache_dir)
    out = {}

    # Scotland and Wales
    table = None
    for chamber in ("scotland", "senedd"):
        term = people.term_start(chamber)
        if not term:
            continue
        previous = (people.term_start(chamber, on=mysociety._minus_days(term, 1))
                    or mysociety._minus_days(term, 5 * 365))
        questions = from_mysociety(cache_dir, chamber, term, previous, offline=not fetch)
        if not questions:
            continue
        if table is None:
            table = mysociety.load_table(cache_dir, "votes")[
                ["division_key", "person_id", "effective_vote"]]
        keys = {q["key"] for q in questions}
        rows = table[table["division_key"].isin(keys)]
        by_key = {}
        for key, pid, vote in rows.itertuples(index=False, name=None):
            if str(vote).lower() != "absent":
                by_key.setdefault(key, {})[int(pid)] = vote_code(vote)
        quiz = build_set(chamber, questions, people.current_members(chamber),
                         lambda q: by_key.get(q["key"], {}),
                         lambda pid, day, c=chamber: people.sat_on(pid, c, day))
        quiz.update(termStart=term, votesAsOf=mysociety.cache_date(cache_dir),
                    source="TheyWorkForYou Votes (mySociety)")
        out[mysociety.CHAMBER_PARLIAMENT[chamber]] = quiz

    # Northern Ireland
    csv = data_dir / "ni_assembly" / "votes_on_division" / "votes_on_division_master.csv"
    term = people.term_start("ni")
    questions, ballots = from_ni_scrape(csv, cache_dir, term, offline=not fetch)
    if questions:
        members = people.current_members("ni")
        # The Assembly's own id for each member is in the register, so its
        # votes are matched to people exactly, never by name.
        by_assembly_id = {m["ids"].get("niassembly"): m["person_id"] for m in members}
        import pandas as pd
        raw = pd.read_csv(csv, dtype=str, usecols=["member_id", "metadata_division_id",
                                                   "metadata_vote_direction", "date"]).fillna("")
        by_division = {}
        for aid, division, vote in zip(raw["member_id"], raw["metadata_division_id"],
                                       raw["metadata_vote_direction"]):
            pid = by_assembly_id.get(aid)
            if pid is not None:
                by_division.setdefault(division, {})[pid] = vote_code(vote)
        quiz = build_set("ni", questions, members,
                         lambda q: by_division.get(q["_division"], {}),
                         lambda pid, day: people.sat_on(pid, "ni", day))
        quiz.update(termStart=term, votesAsOf=max(raw["date"]).split("T")[0],
                    source="Northern Ireland Assembly Open Data")
        out[mysociety.CHAMBER_PARLIAMENT["ni"]] = quiz
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Show the questions each devolved quiz would ask.")
    ap.add_argument("--cache", default=str(mysociety.DEFAULT_CACHE))
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--no-fetch", action="store_true")
    a = ap.parse_args(argv)
    for parliament, quiz in build(Path(a.cache), Path(a.data_dir), fetch=not a.no_fetch).items():
        placed = sum(1 for m in quiz["members"] if sum(p is not None for p in m["pos"]) >= 5)
        print(f"== {parliament}: {len(quiz['statements'])} questions, "
              f"{placed} of {len(quiz['members'])} members voted on five or more")
        for s in quiz["statements"]:
            d = s["divisions"][0]
            print(f"  {d['date']} {s['result'][0]:3}-{s['result'][1]:<3} {s['text'][:96]}")


if __name__ == "__main__":
    main()
