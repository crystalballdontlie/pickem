#!/usr/bin/env python3
"""Offline checks for the update script. Run: python tests/test_update.py"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import update as u  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
failures = 0


def check(label, got, want):
    global failures
    ok = got == want
    failures += not ok
    print(f"{'ok  ' if ok else 'FAIL'} {label}" + ("" if ok else f": got {got!r}, want {want!r}"))


# --- settle / pace logic -------------------------------------------------------
o = u.team_outlook(45, 10, 44.5, 82)          # already past the line
check("over settled once wins pass the line", o["result"], "over")
o = u.team_outlook(10, 45, 40.5, 82)          # max 37 wins
check("under settled once max wins < line", o["result"], "under")
o = u.team_outlook(44, 38, 44.0, 82)
check("whole-number line lands exactly -> push", o["result"], "push")
o = u.team_outlook(20, 20, 41.5, 82)
check("undecided team has no result", o["result"], None)
check("pace = W/GP*82", o["proj"], 41.0)
check("lean under when pace < line", o["lean"], "under")
o = u.team_outlook(0, 0, 41.5, 82)
check("no games -> no pace", (o["proj"], o["lean"]), (None, None))
o = u.team_outlook(41, 41, 41.0, 82)
check("pace equals whole line -> result push at end", o["result"], "push")

check("pick won", u.score_pick("over", {"result": "over", "lean": "over"}), "won")
check("pick lost", u.score_pick("under", {"result": "over", "lean": "over"}), "lost")
check("pick on pace", u.score_pick("under", {"result": None, "lean": "under"}), "on_pace")
check("pick off pace", u.score_pick("over", {"result": None, "lean": "under"}), "off_pace")
check("no pick", u.score_pick(None, {"result": None, "lean": "under"}), "none")

# --- ESPN parsing and aliasing -----------------------------------------------
espn = u.parse_espn(json.loads((FIX / "espn.json").read_text()))
check("ESPN parse finds all 30 teams (GS/NY/UTAH/WSH mapped)", len(espn), 30)

# --- record counting ignores Cup final, playoffs, unplayed, duplicates ------------
games = json.loads((FIX / "bdl_games.json").read_text())
dedup = list({g["id"]: g for g in games}.values())
rec, last = u.count_records(dedup)
check("balldontlie records match independent ESPN tally", u.cross_check(rec, espn)["status"], "match")
bad = u.parse_espn(json.loads((FIX / "espn_mismatch.json").read_text()))
cc = u.cross_check(rec, bad)
check("a disagreement is reported", (cc["status"], len(cc["mismatches"])), ("mismatch", 1))
check("no ESPN data -> 'unavailable', not a failure", u.cross_check(rec, None)["status"], "unavailable")

# --- end-to-end run on the demo pool ---------------------------------------------
out = ROOT / "tests" / "fixtures" / "pool_demo.json"
dedup_path = FIX / "dedup"
dedup_path.mkdir(exist_ok=True)
(dedup_path / "bdl_games.json").write_text(json.dumps(dedup))
(dedup_path / "espn.json").write_text((FIX / "espn.json").read_text())
r = subprocess.run([sys.executable, str(ROOT / "scripts" / "update.py"), "--fixtures", str(dedup_path),
                    "--root", str(FIX / "demo_root"), "--out", str(out)], capture_output=True, text=True)
print(r.stdout.strip())
check("end-to-end run exits cleanly", r.returncode, 0)
p = json.loads(out.read_text())
check("20 players scored", len(p["players"]), 20)
check("every player has 30 pick states", {len(pl["picks"]) for pl in p["players"]}, {30})
pl = p["players"][0]
check("projected = won + on pace", pl["projected"], pl["won"] + pl["on_pace"])
check("ranks start at 1", p["players"][0]["rank"], 1)
check("season label", p["season_label"], "2026-27")

# picks.csv validation
bad_root = FIX / "bad_root"
bad_root.mkdir(exist_ok=True)
for f in ("config.json", "lines.csv"):
    (bad_root / f).write_text((FIX / "demo_root" / f).read_text())
(bad_root / "picks.csv").write_text("name,ATL,XYZ\nPat,O,U\n")
r = subprocess.run([sys.executable, str(ROOT / "scripts" / "update.py"), "--fixtures", str(dedup_path),
                    "--root", str(bad_root), "--out", "/dev/null"], capture_output=True, text=True)
check("unknown team column is rejected with a clear message", "unknown team column 'XYZ'" in r.stderr, True)

# --- Google Form responses ---------------------------------------------------------
import csv as _csv  # noqa: E402
import io as _io  # noqa: E402

demo_lines = u.load_lines(FIX / "demo_root" / "lines.csv")
form_titles = [f"{TEAM}: {demo_lines[a]} wins" for a, (TEAM, _) in sorted(u.TEAMS.items(), key=lambda kv: kv[1][0])]
form_titles[0] = "Atlanta Hawks: 99.5 wins"  # a typo in the form, to trigger the mismatch note
buf = _io.StringIO()
w = _csv.writer(buf)
w.writerow(["Timestamp", "Your name"] + form_titles)
w.writerow(["10/7/2026 19:02:11", "Pat Riley", *(["Over"] * 30)])
w.writerow(["10/7/2026 19:05:40", "Jordan", *(["Under"] * 30)])
w.writerow([""] * 32)                                             # blank row Google sometimes leaves
w.writerow(["10/8/2026 08:15:00", "  pat   riley ", *(["Under"] * 29), "Maybe"])  # resubmission
csv_text = buf.getvalue()
people, notes, n = u.parse_form_csv(csv_text, demo_lines)
by = {p["name"].casefold(): p for p in people}
check("form: resubmission replaces the earlier entry", (len(people), n), (2, 3))
check("form: latest answers win", by["pat riley"]["picks"]["ATL"], "under")
check("form: unrecognized answer left blank", "WAS" in by["pat riley"]["picks"], False)
check("form: all 30 teams found in question titles", len(by["jordan"]["picks"]), 30)
check("form: line typo is reported", any("99.5" in x for x in notes), True)
check("form: odd answer is reported", any("'Maybe'" in x for x in notes), True)

grid = "Timestamp,Name,Picks [Boston Celtics],Picks [Philadelphia 76ers]\nx,Sam,Over,Under\n"
gp, gn, _ = u.parse_form_csv(grid, demo_lines)
check("form: grid-question columns work", gp[0]["picks"], {"BOS": "over", "PHI": "under"})
try:
    u.parse_form_csv("<!DOCTYPE html><html>sign in</html>", demo_lines)
    check("form: a web page instead of CSV is rejected", False, True)
except SystemExit as e:
    check("form: a web page instead of CSV is rejected", "Publish to web" in str(e), True)

form_file = FIX / "form_responses.csv"
form_file.write_text(csv_text)
r = subprocess.run([sys.executable, str(ROOT / "scripts" / "update.py"), "--fixtures", str(dedup_path),
                    "--root", str(FIX / "demo_root"), "--form-csv", str(form_file), "--out", str(out)],
                   capture_output=True, text=True)
check("form: end-to-end run exits cleanly", r.returncode, 0)
p = json.loads(out.read_text())
check("form: page data says where picks came from", p["picks_source"].startswith("2 entries from the Google Form"), True)
check("form: notes reach the page", bool(p["warnings"]), True)

print(f"\n{'All checks passed' if not failures else f'{failures} FAILED'}")
sys.exit(1 if failures else 0)
