#!/usr/bin/env python3
"""
Bias-free behavioural metrics: what each member actually *did*, not what we
think they meant.

Every figure produced here is arithmetic over recorded acts. Nothing in this
module contains a political judgement — there are no pro/con word lists, no
"supportive side" of a division, no opinion about which end of an axis is good.
That is deliberate: see `docs/METHODS.md`.

Methods implemented
    #2  Rebellion     — votes against the member's own party majority
    #3  Ideal points  — unsupervised scaling of the member x division matrix
    #4  Agreement     — how often they vote with their party / with the chamber
    #9  Salience      — what they spend their time on (counts, not stances)
    #10 Participation — divisions voted in vs divisions they could have voted in

Reads the cumulative `*_master.csv` files under `data/<parliament>/…`.

Usage:
    python -m analysis.behaviour
    python -m analysis.behaviour --data-dir data --out analysis/output
    python -m analysis.behaviour --current-only
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

from analysis.grade import (_is_gradeable_name, _norm_name, _slug, load_roster,
                            _VOTED_PREFIX_RE)
from analysis.topics import TOPICS

# --- tunables ---------------------------------------------------------------
# A party's "line" on a division only exists if enough of them voted and the
# split isn't a tie — otherwise "rebelling against it" is meaningless.
MIN_PARTY_VOTERS = 3

# Groupings that are the ABSENCE of a party, not a party. They take no whip, so
# there is no line for them to defy and "rebellion" against them is meaningless
# — without this, independents score as huge rebels purely because other
# independents (who never coordinate) voted differently.
NON_PARTY = {
    "independent", "independent labour", "independent conservative",
    "non-affiliated", "nonaffiliated", "no party affiliation", "none",
    "crossbench", "crossbencher", "bishops", "lord speaker",
    "speaker", "the speaker", "deputy speaker", "presiding officer",
    "deputy presiding officer", "unaffiliated", "other", "",
}


def _is_whipped_group(party: str) -> bool:
    p = (party or "").strip().lower()
    return bool(p) and p not in NON_PARTY and not p.startswith("independent")
# Ideal-point estimation needs members who vote enough to place, and divisions
# that actually divide the chamber (a unanimous vote separates nobody).
MIN_VOTES_FOR_SCALING = 25
MIN_VOTERS_PER_DIVISION = 20
MIN_MINORITY_SIDE = 3
N_DIMENSIONS = 2

# What separates two spells of service: a stretch that is both long AND full of
# divisions the member sat out. Both conditions are needed — a recess is long but
# holds no divisions, and a quiet backbencher misses divisions without ever
# leaving. Only losing a seat produces years of votes they had no part in.
SERVICE_GAP_DAYS = 365
MIN_MISSED_IN_GAP = 40
# Members elected at a general election take their seats over a few weeks. Within
# this window of the election they are measured from the election itself; a first
# vote later than this means they arrived at a by-election.
ELECTION_GRACE_DAYS = 60


def _within_days(a: str, b: str, days: int) -> bool:
    from datetime import date as _date

    def parse(s):
        try:
            return _date(int(s[0:4]), int(s[5:7]), int(s[8:10]))
        except (ValueError, IndexError):
            return None
    da, db = parse(a), parse(b)
    return da is not None and db is not None and abs((da - db).days) <= days


# --- topic keywords only ----------------------------------------------------
# Salience uses ONLY the keyword lists (does this statement mention housing?),
# never the pro/con lists. Assigning a statement to a topic is categorisation;
# deciding which side of it someone is on would be judgement, and is out of
# scope for this module.
def _build_keyword_index():
    index = {}
    for topic, spec in TOPICS.items():
        clean = topic[4:] if topic.startswith("Pro-") else topic
        for kw in spec.get("keywords", ()):
            index.setdefault(kw.lower().strip(), set()).add(clean)
    return index


KEYWORDS = _build_keyword_index()
MAX_KW_NGRAM = max((len(k.split()) for k in KEYWORDS), default=1)
_WORD_RE = re.compile(r"[a-z0-9']+")


def topics_mentioned(text: str) -> set:
    """Topics whose keywords appear in the text. No stance, just presence."""
    tokens = _WORD_RE.findall((text or "").lower())
    found = set()
    for i in range(len(tokens)):
        for n in range(min(MAX_KW_NGRAM, len(tokens) - i), 0, -1):
            hit = KEYWORDS.get(" ".join(tokens[i:i + n]))
            if hit:
                found |= hit
                break
    return found


# --- accumulator ------------------------------------------------------------
def _blank():
    return {
        "name": "", "party": "", "constituency": "", "status": "", "parliament": "",
        "n_questions": 0, "n_speeches": 0,
        "votes_cast": 0, "no_vote_recorded": 0,
        "with_party": 0, "party_line_divisions": 0, "rebellions": 0,
        "with_chamber": 0, "chamber_decided_divisions": 0,
        "first_vote": "", "last_vote": "",
        "vote_dates": Counter(),   # date -> votes cast that day
        "topics": Counter(),
    }


def _read_csv(path: Path, chunksize=20000):
    if not path.exists():
        return
    for chunk in pd.read_csv(path, dtype=str, keep_default_na=False,
                             encoding="utf-8-sig", chunksize=chunksize):
        yield from chunk.to_dict("records")


def _division_key(rec: dict) -> str:
    """Stable id for a division: the source's id, else date+title."""
    did = (rec.get("metadata_division_id", "") or "").strip()
    if did:
        return did
    return (rec.get("date", "")[:10] + "|" + (rec.get("title", "") or "")[:120]).strip()


def analyse(data_dir: Path, out_dir: Path, current_only: bool = False):
    if pd is None or np is None:
        sys.exit("pandas and numpy are required: pip install pandas numpy")

    members: dict = defaultdict(_blank)
    parl_dirs = sorted([p for p in data_dir.iterdir() if p.is_dir()]) if data_dir.exists() else []
    if not parl_dirs:
        sys.exit(f"No parliament folders under {data_dir}/ — run the scraper first.")

    rebellion_rows = []
    scaling = {}   # parliament slug -> (member_keys, ideal points, variance)

    for parl_dir in parl_dirs:
        parl_slug = parl_dir.name
        roster_by_id, roster_by_name = load_roster(parl_dir)

        def resolve(rec):
            """Canonical member key, matching grade.py so outputs join cleanly."""
            info = roster_by_id.get((rec.get("member_id") or "").strip())
            if info is None:
                info = roster_by_name.get(_norm_name(rec.get("member_name", "")))
            if info is None and not _is_gradeable_name(rec.get("member_name", "")):
                return None, None
            if info is not None:
                key = f"{parl_slug}:{info['key']}"
            else:
                nm = _norm_name(rec.get("member_name", ""))
                if not nm:
                    return None, None
                key = f"{parl_slug}:name:{nm}"
            m = members[key]
            if not m["name"]:
                m["name"] = (info or {}).get("name") or rec.get("member_name", "")
                m["party"] = (info or {}).get("party") or rec.get("member_party", "")
                m["constituency"] = (info or {}).get("constituency") or rec.get("member_constituency", "")
                m["status"] = (info or {}).get("status", "")
                m["parliament"] = rec.get("parliament", parl_slug)
            return key, m

        # Seed every sitting member from the roster. Without this a member only
        # exists once they appear in some record, so anyone who never votes and
        # never speaks — an abstentionist MP, a member newly sworn in — silently
        # vanishes from a product whose whole job is "who represents my area".
        seeded = set()
        for info in list(roster_by_id.values()) + list(roster_by_name.values()):
            if info["key"] in seeded or info.get("status") != "current":
                continue
            seeded.add(info["key"])
            m = members[f"{parl_slug}:{info['key']}"]
            if not m["name"]:
                m["name"] = info.get("name", "")
                m["party"] = info.get("party", "")
                m["constituency"] = info.get("constituency", "")
                m["status"] = info.get("status", "")
                # Display name of the legislature is only known once a record
                # arrives; filled in below from whatever the records say.
                m["parliament"] = ""

        def party_at_vote(rec, m):
            """The member's party AT THE TIME OF THE VOTE, where the source says.

            The roster carries a member's party *now*, which is wrong for anyone
            who has since defected, resigned the whip or taken a peerage — their
            old votes would be judged against a line they were never under.
            UK and NI division records carry the contemporaneous party, so
            prefer it; Scotland and the Senedd don't, so those fall back to the
            roster and remain subject to this limitation.
            """
            return (rec.get("member_party") or "").strip() or (m["party"] or "").strip()

        # ---- salience: what they ask and speak about (#9) ----
        for dtype, counter in (("questions", "n_questions"),
                               ("plenary_business", "n_speeches")):
            for rec in _read_csv(parl_dir / dtype / f"{dtype}_master.csv"):
                text = rec.get("text", "") or ""
                if not text:
                    continue
                _, m = resolve(rec)
                if m is None:
                    continue
                m[counter] += 1
                for t in topics_mentioned(text):
                    m["topics"][t] += 1

        # ---- votes: two passes so we know each division's party lines ----
        vote_path = parl_dir / "votes_on_division" / "votes_on_division_master.csv"
        if not vote_path.exists():
            continue

        # Pass 1 — tally each division by party and overall.
        div_party = defaultdict(lambda: defaultdict(Counter))  # div -> party -> dir counts
        div_total = defaultdict(Counter)                        # div -> dir counts
        div_meta = {}
        for rec in _read_csv(vote_path):
            direction = (rec.get("metadata_vote_direction", "") or "").strip().lower()
            key, m = resolve(rec)
            if m is None:
                continue
            if direction not in ("aye", "no"):
                if direction in ("no_vote", "novoterecorded", "not_recorded"):
                    m["no_vote_recorded"] += 1
                continue
            div = _division_key(rec)
            if div not in div_meta:
                div_meta[div] = {
                    "date": (rec.get("date", "") or "")[:10],
                    "title": (rec.get("title", "") or "")
                             or _VOTED_PREFIX_RE.sub("", rec.get("text", "") or ""),
                }
            div_total[div][direction] += 1
            party = party_at_vote(rec, m)
            if _is_whipped_group(party):
                div_party[div][party][direction] += 1

        # Resolve the party line and the chamber result for each division.
        party_line, chamber_line = {}, {}
        for div, by_party in div_party.items():
            for party, c in by_party.items():
                if c["aye"] + c["no"] < MIN_PARTY_VOTERS or c["aye"] == c["no"]:
                    continue  # too few, or genuinely split — no line to rebel against
                party_line[(div, party)] = "aye" if c["aye"] > c["no"] else "no"
        for div, c in div_total.items():
            if c["aye"] != c["no"]:
                chamber_line[div] = "aye" if c["aye"] > c["no"] else "no"

        # Pass 2 — score each member's votes against both baselines (#2, #4, #10).
        vote_triples = []      # (member_key, division_key, +1/-1) for scaling
        for rec in _read_csv(vote_path):
            direction = (rec.get("metadata_vote_direction", "") or "").strip().lower()
            if direction not in ("aye", "no"):
                continue
            key, m = resolve(rec)
            if m is None:
                continue
            div = _division_key(rec)
            date = (rec.get("date", "") or "")[:10]

            m["votes_cast"] += 1
            if date:
                m["vote_dates"][date] += 1
                if not m["first_vote"] or date < m["first_vote"]:
                    m["first_vote"] = date
                if not m["last_vote"] or date > m["last_vote"]:
                    m["last_vote"] = date

            vparty = party_at_vote(rec, m)
            line = party_line.get((div, vparty)) if _is_whipped_group(vparty) else None
            if line:
                m["party_line_divisions"] += 1
                if direction == line:
                    m["with_party"] += 1
                else:
                    m["rebellions"] += 1
                    rebellion_rows.append({
                        "parliament": m["parliament"], "member": m["name"],
                        "party": vparty, "date": date,
                        "division": div_meta.get(div, {}).get("title", ""),
                        "their_vote": direction, "party_voted": line,
                    })

            cline = chamber_line.get(div)
            if cline:
                m["chamber_decided_divisions"] += 1
                if direction == cline:
                    m["with_chamber"] += 1

            vote_triples.append((key, div, 1 if direction == "aye" else -1))

        # ---- participation denominator (#10) ----
        # A member can only vote in divisions held while they actually sat, and
        # plenty of them sit in more than one spell — elected, defeated, elected
        # again years later. Spanning first-to-last vote would charge a returning
        # member for every division held while they were out of the chamber
        # (it credited 44% of sitting UK MPs with divisions from parliaments they
        # were not in). So split the record into spells at long voteless gaps and
        # measure attendance over the CURRENT spell only — which is also the
        # figure a voter wants: how their present representative is doing now.
        dates_only = sorted(meta["date"] for meta in div_meta.values() if meta["date"])
        last_division = dates_only[-1] if dates_only else ""

        # Where does the current term begin? An election puts a large cohort into
        # the chamber on the same day, so the most common spell-start month among
        # sitting members IS the election — no hardcoded dates, no judgement.
        # Without this, a 2024 intake member is judged over 582 divisions and a
        # long-serving one over 2,367, yet both sit against the same median.
        starts = Counter()
        for key, m in members.items():
            if key.startswith(f"{parl_slug}:") and m["status"] == "current" and m["vote_dates"]:
                spells = _service_spells(sorted(m["vote_dates"]), dates_only)
                m["_spells"] = spells
                starts[spells[-1][0][:7]] += 1
        term_start = ""
        if starts:
            top_month = starts.most_common(1)[0][0]
            term_start = min(m["_spells"][-1][0] for m in members.values()
                             if m.get("_spells") and m["_spells"][-1][0][:7] == top_month)

        for key, m in members.items():
            if not key.startswith(f"{parl_slug}:"):
                continue
            if not m["vote_dates"]:
                # Never voted. For a sitting member that is itself the finding —
                # abstentionist parties, for instance — so show 0 of the term,
                # not a blank.
                if m["status"] == "current" and term_start and m["name"]:
                    lo = _bisect_left(dates_only, term_start)
                    m["divisions_eligible"] = len(dates_only) - lo
                    m["term_votes"] = 0
                    m["spells"] = 0
                    m["spell_start"] = term_start
                continue
            spells = m.get("_spells") or _service_spells(sorted(m["vote_dates"]), dates_only)
            m["spells"] = len(spells)
            start, end = spells[-1]
            # Measure over the current term, so every member is compared on the
            # same window. Anyone whose first vote falls within the settling-in
            # period after the election is measured from the election itself —
            # divisions they missed in their first weeks are still missed. Only a
            # genuine later arrival (a by-election) starts their window later.
            if term_start and m["status"] == "current":
                if start < term_start or _within_days(start, term_start, ELECTION_GRACE_DAYS):
                    start = term_start
            # A sitting member is eligible for everything up to the latest
            # division; one who has left, only up to their own last vote — so
            # real recent absence still shows, but departure isn't punished.
            window_end = last_division if m["status"] == "current" else end
            lo = _bisect_left(dates_only, start)
            hi = _bisect_right(dates_only, window_end)
            m["divisions_eligible"] = max(hi - lo, 0)
            m["term_votes"] = sum(n for d, n in m["vote_dates"].items()
                                  if start <= d <= window_end)
            m["divisions_eligible"] = max(m["divisions_eligible"], m["term_votes"])
            m["spell_start"] = start

        # Fill the legislature's display name onto members seeded from the roster
        # that never appeared in a record.
        display = next((m["parliament"] for k, m in members.items()
                        if k.startswith(f"{parl_slug}:") and m["parliament"]), parl_slug)
        for key, m in members.items():
            if key.startswith(f"{parl_slug}:") and not m["parliament"]:
                m["parliament"] = display

        # ---- ideal points (#3) ----
        # Only members who sit together can be placed on one axis. Pooling every
        # member ever pulled would scale people who never shared a division, and
        # the leading dimension would partly separate ERAS rather than positions.
        cohort = {k for k, m in members.items()
                  if k.startswith(f"{parl_slug}:") and m["status"] == "current"}
        scaling[parl_slug] = _ideal_points(
            [t for t in vote_triples if t[0] in cohort])

    _write_outputs(members, rebellion_rows, scaling, out_dir, current_only)


def _service_spells(dates, division_dates=()):
    """Split a member's sorted vote dates into spells of service.

    A break is a gap that is BOTH longer than SERVICE_GAP_DAYS and contains at
    least MIN_MISSED_IN_GAP divisions the member took no part in. Requiring both
    is what separates "lost their seat for a term" from "it was the summer" or
    "they are a quiet backbencher".

    `division_dates` is the sorted list of every division date in that
    legislature. Returns [(start, end), ...]; the last is the current spell.
    """
    from datetime import date as _date

    def parse(s):
        try:
            return _date(int(s[0:4]), int(s[5:7]), int(s[8:10]))
        except (ValueError, IndexError):
            return None

    clean = [s for s in dates if parse(s)]
    if not clean:
        return [(dates[0], dates[-1])] if dates else []

    spells, start, prev_s = [], clean[0], clean[0]
    for s in clean[1:]:
        days = (parse(s) - parse(prev_s)).days
        if days > SERVICE_GAP_DAYS:
            missed = (_bisect_left(division_dates, s)
                      - _bisect_right(division_dates, prev_s))
            if missed >= MIN_MISSED_IN_GAP:
                spells.append((start, prev_s))
                start = s
        prev_s = s
    spells.append((start, prev_s))
    return spells


def _bisect_left(sorted_list, value):
    import bisect
    return bisect.bisect_left(sorted_list, value)


def _bisect_right(sorted_list, value):
    import bisect
    return bisect.bisect_right(sorted_list, value)


def _ideal_points(triples):
    """Unsupervised scaling of the member x division matrix (method #3).

    No labels, no word lists, no human input of any kind — the dimensions fall
    out of who votes with whom. Returns {member_key: (dim1, dim2)} plus the
    share of variance each dimension explains, so we can report how much of the
    voting record a single axis actually accounts for.

    The SIGN of each dimension is mathematically arbitrary (SVD is only defined
    up to sign). We fix it deterministically — largest party on the positive
    side — purely so results are stable between runs. It carries no meaning.
    """
    if not triples:
        return {}, []

    members = sorted({k for k, _, _ in triples})
    divisions = sorted({d for _, d, _ in triples})
    m_idx = {k: i for i, k in enumerate(members)}
    d_idx = {d: i for i, d in enumerate(divisions)}

    M = np.zeros((len(members), len(divisions)), dtype=np.float32)
    for k, d, v in triples:
        M[m_idx[k], d_idx[d]] = v

    # Keep members who vote enough to be placed, and divisions that divide the
    # chamber — a 600-0 vote tells you nothing about who differs from whom.
    voted = M != 0
    keep_d = np.ones(len(divisions), dtype=bool)
    for j in range(len(divisions)):
        col = M[:, j]
        ayes = int((col > 0).sum())
        noes = int((col < 0).sum())
        keep_d[j] = (ayes + noes) >= MIN_VOTERS_PER_DIVISION and min(ayes, noes) >= MIN_MINORITY_SIDE
    keep_m = voted.sum(axis=1) >= MIN_VOTES_FOR_SCALING
    if keep_m.sum() < 3 or keep_d.sum() < 3:
        return {}, []

    M = M[np.ix_(keep_m, keep_d)]
    kept_members = [k for k, keep in zip(members, keep_m) if keep]

    # Centre each division on its own mean over members who voted in it, so an
    # absence reads as "no information" rather than as a vote in the middle.
    for j in range(M.shape[1]):
        col = M[:, j]
        present = col != 0
        if present.any():
            col[present] -= col[present].mean()

    U, S, _ = np.linalg.svd(M, full_matrices=False)
    coords = U[:, :N_DIMENSIONS] * S[:N_DIMENSIONS]
    var = (S ** 2) / (S ** 2).sum()
    explained = [float(v) for v in var[:N_DIMENSIONS]]

    # Scale each dimension to roughly [-1, 1] for display.
    for j in range(coords.shape[1]):
        peak = np.abs(coords[:, j]).max()
        if peak:
            coords[:, j] /= peak

    return {k: (float(coords[i, 0]), float(coords[i, 1]))
            for i, k in enumerate(kept_members)}, explained


def _pct(n, d):
    return round(100.0 * n / d, 1) if d else ""


def _write_outputs(members, rebellion_rows, scaling, out_dir: Path, current_only: bool):
    out_dir.mkdir(parents=True, exist_ok=True)

    # Orient each parliament's first dimension so the largest party sits on the
    # positive side. Arbitrary, deterministic, and meaningless — documented as
    # such so nobody reads "positive" as "good" or "right-wing".
    for parl_slug, (points, _explained) in scaling.items():
        if not points:
            continue
        by_party = defaultdict(list)
        for key, (d1, _d2) in points.items():
            m = members.get(key)
            if m and m["party"]:
                by_party[m["party"]].append(d1)
        if by_party:
            biggest = max(by_party.items(), key=lambda kv: len(kv[1]))
            if sum(biggest[1]) < 0:
                scaling[parl_slug] = ({k: (-a, -b) for k, (a, b) in points.items()},
                                      _explained)

    rows = []
    for key, m in sorted(members.items(), key=lambda kv: (kv[1]["parliament"], kv[1]["name"])):
        if current_only and m["status"] != "current":
            continue
        if not m["name"]:
            continue
        parl_slug = key.split(":", 1)[0]
        points = scaling.get(parl_slug, ({}, []))[0]
        d1, d2 = points.get(key, ("", ""))
        eligible = m.get("divisions_eligible", 0)
        top = m["topics"].most_common(3)
        spoken = m["n_questions"] + m["n_speeches"]
        rows.append({
            "parliament": m["parliament"], "member": m["name"], "party": m["party"],
            "constituency": m["constituency"], "status": m["status"],
            # participation (#10) — turnout is over the CURRENT spell of service,
            # so a returning member isn't charged for their years out
            "votes_cast": m["votes_cast"],
            "spells_served": m.get("spells", 1 if m["votes_cast"] else 0),
            "current_spell_from": m.get("spell_start", ""),
            "term_votes": m.get("term_votes", 0),
            "divisions_eligible": eligible,
            "turnout_pct": _pct(m.get("term_votes", 0), eligible),
            "no_vote_recorded": m["no_vote_recorded"],
            # agreement (#4) — both baselines, shown separately
            "party_agreement_pct": _pct(m["with_party"], m["party_line_divisions"]),
            "party_line_divisions": m["party_line_divisions"],
            "chamber_agreement_pct": _pct(m["with_chamber"], m["chamber_decided_divisions"]),
            "chamber_decided_divisions": m["chamber_decided_divisions"],
            # rebellion (#2)
            "rebellions": m["rebellions"],
            "rebellion_rate_pct": _pct(m["rebellions"], m["party_line_divisions"]),
            # scaling (#3)
            "ideal_dim1": round(d1, 4) if d1 != "" else "",
            "ideal_dim2": round(d2, 4) if d2 != "" else "",
            # salience (#9)
            "n_questions": m["n_questions"], "n_speeches": m["n_speeches"],
            "top_topic_1": top[0][0] if len(top) > 0 else "",
            "top_topic_2": top[1][0] if len(top) > 1 else "",
            "top_topic_3": top[2][0] if len(top) > 2 else "",
            "top_topic_1_share_pct": _pct(top[0][1], spoken) if top and spoken else "",
        })

    _dump(out_dir / "member_record.csv", rows)

    sal = []
    for key, m in members.items():
        if current_only and m["status"] != "current":
            continue
        spoken = m["n_questions"] + m["n_speeches"]
        for topic, n in sorted(m["topics"].items(), key=lambda kv: -kv[1]):
            sal.append({"parliament": m["parliament"], "member": m["name"],
                        "topic": topic, "statements": n,
                        "share_of_statements_pct": _pct(n, spoken)})
    _dump(out_dir / "member_salience.csv", sal)

    rebellion_rows.sort(key=lambda r: (r["parliament"], r["member"], r["date"]))
    _dump(out_dir / "member_rebellions.csv", rebellion_rows)

    print(f"Wrote {len(rows)} members -> {out_dir}/member_record.csv")
    print(f"      {len(rebellion_rows):,} rebellions -> {out_dir}/member_rebellions.csv")
    print(f"      {len(sal):,} member-topic rows -> {out_dir}/member_salience.csv")
    for parl_slug, (points, explained) in sorted(scaling.items()):
        if explained:
            pcts = ", ".join(f"dim{i+1} {v:.1%}" for i, v in enumerate(explained))
            print(f"  scaling {parl_slug}: {len(points)} members placed ({pcts} of variance)")
        else:
            print(f"  scaling {parl_slug}: not enough division variety to place members")


def _dump(path: Path, rows):
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Bias-free behavioural metrics.")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--out", dest="out_dir", default="analysis/output")
    ap.add_argument("--current-only", action="store_true")
    a = ap.parse_args(argv)
    analyse(Path(a.data_dir), Path(a.out_dir), current_only=a.current_only)


if __name__ == "__main__":
    main()
