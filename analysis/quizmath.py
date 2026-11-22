#!/usr/bin/env python3
"""
The quiz arithmetic, in one place, in plain Python.

The website (app/index.html) and the phone app (mobile/lib/core/scoring.dart)
each implement these rules in their own language. This file is the reference
they are held to:

    python -m analysis.quizmath

writes mobile/test/fixtures/quiz_slice.json: a small frozen slice of the real
quiz, some answers, and what these functions make of them. The phone app's
tests must reproduce every number in it, and tests/test_quizmath.py fails if
the file no longer matches this code. Change a rule here and both follow, or
the tests say so.

The rules
---------
Agreement on one statement, where both you and the member have a view:

    1 - |you - them| / 2          1 = the same view, 0 = opposite

A match is the average of that over the statements you both have a view on,
counting twice any you marked as mattering a lot.

Two tests decide what is done with it.

  * SHOWN, to the member's own constituents and to anyone who looks them up:
    when it rests on at least five such statements (or all you answered, if
    fewer). The figure always comes with how many statements it rests on.

  * RANKED, in a list of who voted most like you, and counted in a party's
    average: when it is shown AND rests on at least half of the statements
    you answered THAT THE MEMBER COULD HAVE VOTED ON.

The second test is about fairness between members. Someone elected in 2024
cannot have voted on tuition fees in 2004; that is not a gap in their record
and must not count against them. But someone who was a member and did not
vote has left a gap. An MP from Northern Ireland or Scotland who stays out of
votes on laws for England may have voted on a third of what you answered: a
person they represent should still see that figure, and what it rests on. It
should not sit in a ranking above members with a full record, where five
lucky agreements would beat thirty real ones.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

MIN_ANSWERS = 5
FOR, AGAINST, ABSTAIN, ABSENT, NOT_MEMBER = "f", "a", "b", "x", "."
_THERE = {FOR, AGAINST, ABSTAIN, ABSENT}


def could_vote(codes: str) -> bool:
    """Whether the member sat during at least one of a statement's votes."""
    return any(c in _THERE for c in codes or "")


def match(positions: list, votes: list, answers: dict) -> dict:
    """Agreement between a set of answers and one member.

    positions[i]  the member's position on statement i (-1..1), or None
    votes[i]      their vote codes on statement i, one character per division
    answers       {i: (value, matters_a_lot)}; value None means not answered
    """
    total = weight = 0.0
    overlap = eligible = 0
    for i, (value, important) in answers.items():
        if value is None:
            continue
        if could_vote(votes[i] if i < len(votes) else ""):
            eligible += 1
        them = positions[i] if i < len(positions) else None
        if them is None:
            continue
        w = 2.0 if important else 1.0
        total += w * (1 - abs(value - them) / 2)
        weight += w
        overlap += 1
    return {"pct": 100 * total / weight if weight else None,
            "overlap": overlap, "eligible": eligible}


def shown(m: dict, answered: int) -> bool:
    """Whether a match rests on enough to be shown at all."""
    return m["pct"] is not None and m["overlap"] >= min(answered, MIN_ANSWERS)


def enough(m: dict, answered: int) -> bool:
    """Whether a match also covers enough of what the member could have voted
    on to be ranked against other members' and averaged into a party's."""
    return shown(m, answered) and m["overlap"] * 2 >= m["eligible"]


def place(statements: list, value_at) -> dict:
    """Where a set of positions sits on the two compass axes.

    The SAME function places a visitor (from their answers) and a member
    (from their votes). `value_at(i)` is the position on statement i, or None.
    """
    e = en = s = sn = 0.0
    for i, st in enumerate(statements):
        v = value_at(i)
        if v is None:
            continue
        if st.get("econ"):
            e += st["econ"] * v
            en += abs(st["econ"])
        if st.get("social"):
            s += st["social"] * v
            sn += abs(st["social"])
    return {"econ": e / en if en else None, "social": s / sn if sn else None,
            "econWeight": en, "socialWeight": sn}


def _rotate_subjects(statements: list, indices: list) -> list:
    groups, names = {}, []
    for i in indices:
        g = statements[i].get("group", "")
        if g not in groups:
            groups[g] = []
            names.append(g)
        groups[g].append(i)
    for g in names:
        groups[g].sort(key=lambda i: (-statements[i].get("termVotes", 0),
                                      -len(statements[i].get("divisions", [])), i))
    names.sort(key=lambda g: (-len(groups[g]), g))
    out, left = [], True
    while left:
        left = False
        for g in names:
            if groups[g]:
                out.append(groups[g].pop(0))
                left = True
    return out


def asking_order(statements: list) -> list:
    """The order statements are asked in.

    Three lanes taken in turn - those that place you on the social axis, on
    the economic axis, and the rest - so that nine answers are enough for a
    compass position. Within a lane subjects rotate, best-evidenced first, so
    that stopping early still leaves a spread.
    """
    lanes = [[], [], []]
    for i, s in enumerate(statements):
        lanes[0 if s.get("social") else 1 if s.get("econ") else 2].append(i)
    rotated = [_rotate_subjects(statements, lane) for lane in lanes]
    out, left = [], True
    while left:
        left = False
        for lane in rotated:
            if lane:
                out.append(lane.pop(0))
                left = True
    return out


def full_order(core: list, more: list) -> list:
    """This parliament's statements first, then the earlier ones, each in
    its own asking order. Indices are into core + more."""
    return asking_order(core) + [len(core) + i for i in asking_order(more)]


# --------------------------------------------------------------------------
# The frozen slice
# --------------------------------------------------------------------------
FIXTURE = Path(__file__).resolve().parent.parent / "mobile" / "test" / "fixtures" / "quiz_slice.json"
_SCALE = [1, 0.5, -1, None, -0.5, 1, 0, -1, 0.5, 1, -0.5, 0.5]      # None = skipped


def _round(v):
    return None if v is None else round(v, 9)


def expected(quiz: dict, answers: dict) -> dict:
    """Everything the apps must reproduce for this quiz and these answers."""
    core, more = quiz["statements"], quiz.get("moreStatements", [])
    statements = core + more
    by_index = {i: (answers[str(s["id"])]["v"], bool(answers[str(s["id"])].get("imp")))
                for i, s in enumerate(statements) if str(s["id"]) in answers}
    answered = sum(1 for v, _ in by_index.values() if v is not None)

    def one(m: dict) -> dict:
        blanks = [None] * len(more)
        pos = m["pos"] + m.get("morePos", blanks)
        votes = m["votes"] + m.get("moreVotes", [""] * len(more))
        r = match(pos, votes, by_index)
        c = place(statements, lambda i: pos[i])
        return {"pct": _round(r["pct"]), "overlap": r["overlap"], "eligible": r["eligible"],
                "shown": shown(r, answered), "enough": enough(r, answered),
                "compass": [_round(c["econ"]), _round(c["social"]), c["econWeight"], c["socialWeight"]]}

    you = place(statements, lambda i: by_index.get(i, (None, False))[0])
    return {
        "answered": answered,
        "order": full_order(core, more),
        "you": [_round(you["econ"]), _round(you["social"]), you["econWeight"], you["socialWeight"]],
        "members": {str(m["id"]): one(m) for m in quiz["members"] + quiz.get("former", [])},
    }


def make_fixture(quiz: dict) -> dict:
    """A slice of the real quiz small enough to read, wide enough to matter:
    statements on both axes and neither, from this parliament and before it;
    members who are new, long-serving, abstentionist, gone, and one who was
    there throughout but voted on under half of it."""
    def pick(statements: list, n: int) -> list:
        tagged_e = [s for s in statements if s["econ"]][: n // 3 + 1]
        tagged_s = [s for s in statements if s["social"]][: n // 3 + 1]
        rest = [s for s in statements if not s["econ"] and not s["social"]][: n // 3 + 1]
        chosen = {s["id"]: s for s in tagged_e + tagged_s + rest}
        return [s for s in statements if s["id"] in chosen][:n]

    core, more = pick(quiz["statements"], 8), pick(quiz["moreStatements"], 6)
    ci = [i for i, s in enumerate(quiz["statements"]) if s in core]
    mi = [i for i, s in enumerate(quiz["moreStatements"]) if s in more]

    def cut(m: dict) -> dict:
        out = {k: m[k] for k in ("id", "name", "party", "area") if k in m}
        out["pos"] = [m["pos"][i] for i in ci]
        out["votes"] = [m["votes"][i] for i in ci]
        if "morePos" in m:
            out["morePos"] = [m["morePos"][i] for i in mi]
            out["moreVotes"] = [m["moreVotes"][i] for i in mi]
        return out

    answers = {}
    for n, s in enumerate(core + more):
        v = _SCALE[n % len(_SCALE)]
        if n == len(core) + len(more) - 1:
            continue                                   # one left unanswered
        answers[str(s["id"])] = {"v": v, "skipped": v is None, "imp": v is not None and n % 4 == 2}
    by_index = {i: (answers[str(s["id"])]["v"], bool(answers[str(s["id"])].get("imp")))
                for i, s in enumerate(core + more) if str(s["id"]) in answers}
    answered = sum(1 for v, _ in by_index.values() if v is not None)

    def partial(m: dict) -> bool:
        """Shown but not ranked: there for most of it, voted on under half."""
        c = cut(m)
        r = match(c["pos"] + c.get("morePos", [None] * len(more)),
                  c["votes"] + c.get("moreVotes", [""] * len(more)), by_index)
        return shown(r, answered) and not enough(r, answered)

    sitting = quiz["members"]
    new = [m for m in sitting if "morePos" not in m and any(p is not None for p in m["pos"])]
    veterans = sorted((m for m in sitting if "morePos" in m),
                      key=lambda m: -sum(p is not None for p in m["morePos"]))
    silent = [m for m in sitting if not any(p is not None for p in m["pos"])]
    chosen = new[:3] + veterans[:3] + veterans[-2:] + silent[:1] + [m for m in sitting if partial(m)][:1]
    members = [cut(m) for m in {m["id"]: m for m in chosen}.values()]
    former = [cut(m) for m in sorted(quiz["former"],
                                     key=lambda m: -sum(p is not None for p in m.get("morePos", [])))[:2]]
    slice_ = {"termStart": quiz["termStart"], "votesAsOf": quiz["votesAsOf"],
              "statements": core, "moreStatements": more, "members": members, "former": former}
    return {
        "_about": ("A frozen slice of app/quiz.json. `expected` is what analysis/quizmath.py makes "
                   "of `answers`; the phone app's tests must reproduce it. Regenerate with: "
                   "python -m analysis.quizmath"),
        "quiz": slice_,
        "answers": answers,
        "expected": expected(slice_, answers),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Write the frozen slice the apps are tested against.")
    ap.add_argument("--quiz", default="app/quiz.json")
    ap.add_argument("--out", default=str(FIXTURE))
    a = ap.parse_args(argv)
    fixture = make_fixture(json.loads(Path(a.quiz).read_text(encoding="utf-8")))
    Path(a.out).write_text(json.dumps(fixture, ensure_ascii=False, indent=1), encoding="utf-8")
    e = fixture["expected"]
    print(f"Wrote {a.out}: {len(fixture['quiz']['statements'])}+"
          f"{len(fixture['quiz']['moreStatements'])} statements, {len(e['members'])} people, "
          f"{sum(1 for m in e['members'].values() if m['shown'])} with a match to show, "
          f"{sum(1 for m in e['members'].values() if m['enough'])} of them ranked")


if __name__ == "__main__":
    main()
