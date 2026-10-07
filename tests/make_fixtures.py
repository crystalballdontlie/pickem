#!/usr/bin/env python3
"""Builds fake-but-realistic API responses for offline testing and the demo page.
Simulates a season about 70% complete, shaped exactly like balldontlie's
/v1/games data and ESPN's standings JSON, plus a demo pool of 20 people."""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from update import TEAMS  # noqa: E402

HERE = Path(__file__).resolve().parent
FIX = HERE / "fixtures"
DEMO = FIX / "demo_root"
ESPN_CODES = {"GSW": "GS", "NOP": "NO", "NYK": "NY", "SAS": "SA", "UTA": "UTAH", "WAS": "WSH"}

rng = random.Random(7)
abbrs = sorted(TEAMS)
strength = {t: rng.uniform(0.25, 0.75) for t in abbrs}
lines = {t: round(strength[t] * 82 - 0.5) + 0.5 for t in abbrs}
lines["MEM"] = 44.0  # a whole-number line, to exercise pushes

games, gid = [], 1000


def team_obj(t):
    name, conf = TEAMS[t]
    return {"id": abbrs.index(t) + 1, "conference": conf, "abbreviation": t, "full_name": name}


def add(day, home, away, **extra):
    global gid
    gid += 1
    p = strength[home] / (strength[home] + strength[away]) + 0.03
    hs = rng.randint(100, 130)
    vs = hs - rng.randint(1, 15) if rng.random() < p else hs + rng.randint(1, 15)
    g = {"id": gid, "date": day, "season": 2026, "status": "Final", "status_state": "final",
         "postseason": False, "postponed": False, "ist_stage": None,
         "home_team_score": hs, "visitor_team_score": vs,
         "home_team": team_obj(home), "visitor_team": team_obj(away)}
    g.update(extra)
    games.append(g)
    return g


# ~57 games per team
for rnd in range(57):
    order = abbrs[:]
    rng.shuffle(order)
    day = f"2027-{1 + rnd // 28:02d}-{1 + rnd % 28:02d}"
    for i in range(0, 30, 2):
        add(day, order[i], order[i + 1])

# Things the script must ignore:
add("2026-12-16", "BOS", "OKC", ist_stage="Championship")                 # NBA Cup final
add("2027-02-28", "LAL", "DEN", status="7:30 pm ET", status_state="scheduled",
    home_team_score=0, visitor_team_score=0)                              # not played yet
add("2027-02-28", "MIA", "NYK", postseason=True)                          # playoff game
dup = dict(games[0])                                                      # same game in both feeds
games.append(dup)

FIX.mkdir(exist_ok=True)
(FIX / "bdl_games.json").write_text(json.dumps(games))

# ESPN standings: computed independently from the same games
rec = {t: [0, 0] for t in abbrs}
seen = set()
for g in games:
    if g["id"] in seen or g["postseason"] or g["ist_stage"] == "Championship" or g["status_state"] != "final":
        continue
    seen.add(g["id"])
    h, a = g["home_team"]["abbreviation"], g["visitor_team"]["abbreviation"]
    w, l = (h, a) if g["home_team_score"] > g["visitor_team_score"] else (a, h)
    rec[w][0] += 1
    rec[l][1] += 1


def entry(t):
    return {"team": {"abbreviation": ESPN_CODES.get(t, t), "displayName": TEAMS[t][0]},
            "stats": [{"name": "wins", "value": float(rec[t][0])},
                      {"name": "losses", "value": float(rec[t][1])},
                      {"name": "winPercent", "value": 0.5}]}


espn = {"children": [
    {"name": "Eastern Conference", "standings": {"entries": [entry(t) for t in abbrs if TEAMS[t][1] == "East"]}},
    {"name": "Western Conference", "standings": {"entries": [entry(t) for t in abbrs if TEAMS[t][1] == "West"]}},
]}
(FIX / "espn.json").write_text(json.dumps(espn))

# A version where ESPN disagrees about one team, to test the warning
espn_bad = json.loads(json.dumps(espn))
espn_bad["children"][0]["standings"]["entries"][0]["stats"][0]["value"] += 1
(FIX / "espn_mismatch.json").write_text(json.dumps(espn_bad))

# Demo pool: 20 people with plausible picks
DEMO.mkdir(exist_ok=True)
(DEMO / "config.json").write_text(json.dumps({"pool_name": "Demo Over/Under Pool", "season": 2026, "games_per_team": 82, "demo": True}, indent=2))
with (DEMO / "lines.csv").open("w") as f:
    f.write("team,line\n")
    for t in abbrs:
        f.write(f"{t},{lines[t]}\n")
names = ["Alex", "Bri", "Carlos", "Dana", "Eli", "Fatima", "Gus", "Hana", "Ivan", "Jess",
         "Kofi", "Lena", "Marco", "Nia", "Omar", "Priya", "Quinn", "Rosa", "Sam", "Tariq"]
with (DEMO / "picks.csv").open("w") as f:
    f.write("name," + ",".join(abbrs) + "\n")
    for n in names:
        skill = rng.uniform(0.45, 0.65)
        row = []
        for t in abbrs:
            truth_over = rec[t][0] / sum(rec[t]) * 82 > lines[t]
            right = rng.random() < skill
            row.append("O" if truth_over == right else "U")
        f.write(n + "," + ",".join(row) + "\n")
print(f"fixtures: {len(games)} game rows, demo pool of {len(names)}")
