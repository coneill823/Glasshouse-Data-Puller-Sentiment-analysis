#!/usr/bin/env python3
"""
What the website should show, worked out by the reference arithmetic.

The page (app/index.html) has no build step and no test runner. This and
check.js are how it is held to analysis/quizmath.py: this script answers most
of the House of Commons statements and of one devolved legislature's votes,
for a place with an MP and several devolved members, and writes down every
figure the page should then show. check.js opens the page in a real browser
with the same answers and compares.

    python app/check/reference.py > want.json
    node app/check/check.js app want.json          # needs: npm install playwright

Nothing here is specific to today's data: the place, the people and the
council are read from the files, so it keeps working as they change.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from analysis import quizmath as qm  # noqa: E402

UK = "UK Parliament"
SCALE = [1, 0.5, -0.5, -1, 0.5, 0, 1, -1, 0.5, -0.5]


def js_round(x: float) -> int:
    """Math.round, which rounds halves up; Python's round does not."""
    return int(x + 0.5)


def main() -> None:
    d = json.loads((ROOT / "app" / "data.json").read_text(encoding="utf-8"))
    q = json.loads((ROOT / "app" / "quiz.json").read_text(encoding="utf-8"))
    more = q["moreStatements"]

    # A council that was read and one of its wards; and a place with an MP and
    # several devolved members. The page finds Assembly seats from a postcode
    # by the name of the Commons seat, so the two must share one.
    body = next(b for b in d["councils"]["bodies"] if b["attendance"])
    ward = body["wards"][0]
    devolved = "NI Assembly"
    chamber = q["chambers"][devolved]
    areas = {}
    for m in chamber["members"]:
        areas.setdefault(m["area"], []).append(m)

    def commons_seat(name):
        return next((x for x in d["members"] if x["parliament"] == UK
                     and x["area"] in (name, name + " and Mid Down")), None)

    shared = [a for a in sorted(areas) if commons_seat(a)]
    area = "Belfast South" if "Belfast South" in shared else shared[0]
    mp = commons_seat(area)

    answers = {}
    for i, s in enumerate(q["statements"]):
        if i % 9 != 8:
            answers[str(s["id"])] = {"v": SCALE[i % 10], "imp": i % 7 == 0}
    for i, s in enumerate(chamber["statements"]):
        if i % 11 != 10:
            answers[str(s["id"])] = {"v": SCALE[(i * 3) % 10], "imp": i % 6 == 0}

    def figures(statements, members, blanks=0):
        by_index = {i: (answers[str(s["id"])]["v"], answers[str(s["id"])]["imp"])
                    for i, s in enumerate(statements) if str(s["id"]) in answers}
        out = {}
        for m in members:
            r = qm.match(m["pos"] + m.get("morePos", [None] * blanks),
                         m["votes"] + m.get("moreVotes", [""] * blanks), by_index)
            out[m["id"]] = (m, r, qm.shown(r, len(by_index)), qm.enough(r, len(by_index)))
        return out, len(by_index)

    commons, _ = figures(q["statements"] + more, q["members"], len(more))
    theirs, answered = figures(chamber["statements"], chamber["members"])

    def row(r, shown, enough, things):
        if not shown:
            return {"v": "—", "basis": "has not voted on these" if r["overlap"] == 0 and r["eligible"]
                    else "was not a member for these votes" if not r["eligible"] else "too few votes in common"}
        return {"v": f"{js_round(r['pct'])}%",
                "basis": f"{r['overlap']} {things} in common" if enough
                else f"voted on {r['overlap']} of {r['eligible']} {things} they could have"}

    reps = {}
    m, r, shown, enough = commons[mp["id"]]
    reps[m["name"]] = row(r, shown, enough, "statements")
    for x in areas[area]:
        m, r, shown, enough = theirs[x["id"]]
        reps[m["name"]] = row(r, shown, enough, "votes")

    def top(figs):
        # ties keep the order of the data, as a stable sort does in the page
        ranked = sorted((v for v in figs.values() if v[3]), key=lambda v: (-v[1]["pct"], -v[1]["overlap"]))
        return [f"{m['name']} {js_round(r['pct'])}%" for m, r, _, _ in ranked[:6]]

    with_figure = sorted((theirs[x["id"]] for x in areas[area] if theirs[x["id"]][2]),
                         key=lambda v: -v[1]["pct"])
    sitting_names = [x["name"].lower() for x in d["members"]]
    former = next(x for x in d["others"]
                  if x["status"] == "former" and x["parliament"] == UK
                  and sum(1 for y in d["others"] + d["members"] if y["id"] == x["id"]) == 1
                  and not any(x["name"].lower() in n for n in sitting_names))
    peer = next(x for x in d["others"] if x["status"] == "peer" and x["party"] == "Crossbench"
                and x["rebellions"] > 0 and (x.get("termVotes") or 0) > 0)
    ballot = next((b for b in d["elections"]["ballots"] if b["candidates"]), None)
    tagged = sum(1 for s in q["statements"] + more if s["econ"] or s["social"])
    councils = [b["name"].replace(" City Council", "").replace(" Council", "") for b in d["councils"]["bodies"]]
    house = d["chambers"][devolved]["house"]
    slug = "blk-" + "-".join("".join(c if c.isalnum() else " " for c in devolved.lower()).split())

    json.dump({
        "postcode": {"postcode": "ZZ1 1ZZ", "country": "Northern Ireland",
                     "parliamentary_constituency_2024": mp["area"], "admin_ward": ward["covers"][0],
                     "codes": {"parliamentary_constituency_2024": mp["gss"], "admin_district": body["gss"],
                               "admin_ward": "X00000001", "admin_county": "X99999999"}},
        "devolved": {"parliament": devolved, "house": house, "role": d["chambers"][devolved]["role"],
                     "block": slug, "count": len(chamber["statements"]), "answered": answered,
                     "other": with_figure[1][0]["name"] if len(with_figure) > 1 else with_figure[0][0]["name"]},
        "coreCount": len(q["statements"]),
        "council": {"ward": ward["name"], "within": ward["covers"][0]},
        "saved": {"answers": answers, "ats": {"commons": 3}, "section": "commons", "mp": None, "started": False,
                  "place": {"label": "ZZ1 1ZZ", "keys": [f"{UK}||{mp['area']}", f"{devolved}||{area}"], "notes": [],
                            "codes": [body["gss"]], "ward": ward["covers"][0], "district": body["gss"]}},
        "legacy": {"answers": {str(s["id"]): {"v": 1, "imp": False} for s in q["statements"][:3]},
                   "at": 3, "started": True, "place": None, "mp": None},
        "mp": mp["name"], "reps": reps, "top": {"blk-uk-parliament": top(commons), slug: top(theirs)},
        "former": {"name": former["name"], "years": f"{former['since']}–{former['until']}"},
        "peer": {"name": peer["name"]},
        "candidate": None if ballot is None else {
            "name": ballot["candidates"][0]["name"],
            "where": ballot["body"] if not ballot["area"] or ballot["area"] == ballot["body"]
            else f"{ballot['area']}, {ballot['body']}"},
        "method": [
            f"The {len(q['statements'])} statements about this parliament and the {len(more)} about earlier ones",
            f"{len(chamber['statements'])} for the {house}",
            f"{tagged} are, and {len(q['statements']) + len(more) - tagged} that do not",
            f"{sum(1 for x in d['others'] if x['status'] == 'former'):,} former MPs, MSPs and MSs",
            f"{sum(1 for x in d['others'] if x['status'] == 'peer'):,} members of the House of Lords",
            "with " + (" and ".join([", ".join(councils[:-1]), councils[-1]]) if len(councils) > 1 else councils[0]) + " so far",
        ],
    }, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
