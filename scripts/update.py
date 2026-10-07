#!/usr/bin/env python3
"""
Nightly update for the NBA over/under pool.

1. Pulls every final regular-season game from balldontlie (free tier) and
   counts wins/losses per team.
2. Cross-checks those records against ESPN's public standings endpoint.
3. Scores everyone's over/under picks and writes site/data/pool.json,
   which the static site reads.

Standard library only, so the GitHub Action needs no pip install.

Usage:
  BALLDONTLIE_API_KEY=... python scripts/update.py
  python scripts/update.py --fixtures tests/fixtures      # offline test run
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BDL_GAMES_URL = "https://api.balldontlie.io/v1/games"
ESPN_STANDINGS_URL = "https://site.api.espn.com/apis/v2/sports/basketball/nba/standings"

# Free tier allows 5 requests/minute; 13s between calls stays safely under it.
BDL_REQUEST_GAP_SECONDS = 13

# Canonical NBA abbreviations -> (display name, conference)
TEAMS = {
    "ATL": ("Atlanta Hawks", "East"), "BOS": ("Boston Celtics", "East"),
    "BKN": ("Brooklyn Nets", "East"), "CHA": ("Charlotte Hornets", "East"),
    "CHI": ("Chicago Bulls", "East"), "CLE": ("Cleveland Cavaliers", "East"),
    "DAL": ("Dallas Mavericks", "West"), "DEN": ("Denver Nuggets", "West"),
    "DET": ("Detroit Pistons", "East"), "GSW": ("Golden State Warriors", "West"),
    "HOU": ("Houston Rockets", "West"), "IND": ("Indiana Pacers", "East"),
    "LAC": ("LA Clippers", "West"), "LAL": ("Los Angeles Lakers", "West"),
    "MEM": ("Memphis Grizzlies", "West"), "MIA": ("Miami Heat", "East"),
    "MIL": ("Milwaukee Bucks", "East"), "MIN": ("Minnesota Timberwolves", "West"),
    "NOP": ("New Orleans Pelicans", "West"), "NYK": ("New York Knicks", "East"),
    "OKC": ("Oklahoma City Thunder", "West"), "ORL": ("Orlando Magic", "East"),
    "PHI": ("Philadelphia 76ers", "East"), "PHX": ("Phoenix Suns", "West"),
    "POR": ("Portland Trail Blazers", "West"), "SAC": ("Sacramento Kings", "West"),
    "SAS": ("San Antonio Spurs", "West"), "TOR": ("Toronto Raptors", "East"),
    "UTA": ("Utah Jazz", "West"), "WAS": ("Washington Wizards", "East"),
}

# ESPN and people typing picks use other codes; map them to the canonical ones.
ALIASES = {
    "GS": "GSW", "NO": "NOP", "NOR": "NOP", "NY": "NYK", "SA": "SAS",
    "UTAH": "UTA", "WSH": "WAS", "PHO": "PHX", "BRK": "BKN", "BRO": "BKN",
    "CHO": "CHA", "LA": "LAC",
}


def norm_team(code: str) -> str:
    c = (code or "").strip().upper()
    return ALIASES.get(c, c)


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def http_json(url: str, headers: dict | None = None, retries: int = 5) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "nba-ou-pool/1.0", **(headers or {})})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise SystemExit(
                    "balldontlie returned 401: the API key is missing or invalid. "
                    "Set the BALLDONTLIE_API_KEY repository secret."
                ) from e
            if e.code == 429 or e.code >= 500:
                wait = 30 * (attempt + 1)
                print(f"  HTTP {e.code} from {url.split('?')[0]}; retrying in {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
        except urllib.error.URLError as e:
            wait = 10 * (attempt + 1)
            print(f"  network error ({e.reason}); retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"Giving up on {url.split('?')[0]} after {retries} attempts")


# --------------------------------------------------------------------------- #
# balldontlie: primary source
# --------------------------------------------------------------------------- #
def fetch_bdl_games(season: int, api_key: str) -> list[dict]:
    """All games for the season from the 'regular' and 'ist' (NBA Cup) feeds,
    de-duplicated by id. Cup group/knockout games count in the standings; the
    Cup championship game does not, and is filtered out in count_records()."""
    games: dict[int, dict] = {}
    first = True
    for season_type in ("regular", "ist"):
        cursor = None
        while True:
            params = [("seasons[]", season), ("season_type", season_type), ("per_page", 100)]
            if cursor:
                params.append(("cursor", cursor))
            url = f"{BDL_GAMES_URL}?{urllib.parse.urlencode(params)}"
            if not first:
                time.sleep(BDL_REQUEST_GAP_SECONDS)
            first = False
            try:
                page = http_json(url, {"Authorization": api_key})
            except urllib.error.HTTPError as e:
                if season_type == "ist" and e.code == 400:
                    print("  'ist' season_type not accepted; relying on the regular feed", file=sys.stderr)
                    break
                raise
            for g in page.get("data", []):
                games[g["id"]] = g
            cursor = (page.get("meta") or {}).get("next_cursor")
            print(f"  balldontlie {season_type}: {len(games)} games so far")
            if not cursor:
                break
    return list(games.values())


def is_final(game: dict) -> bool:
    state = game.get("status_state")
    if state:
        return state == "final"
    return str(game.get("status", "")).lower().startswith("final")


def counts_in_standings(game: dict) -> bool:
    if game.get("postseason"):
        return False
    if (game.get("ist_stage") or "").lower() == "championship":
        return False  # NBA Cup final doesn't count toward the 82-game record
    return is_final(game)


def count_records(games: list[dict]) -> tuple[dict[str, dict], str | None]:
    rec = {abbr: {"w": 0, "l": 0} for abbr in TEAMS}
    last_date = None
    seen: set = set()
    for g in games:
        if g.get("id") in seen or not counts_in_standings(g):
            continue
        seen.add(g.get("id"))
        home = norm_team(g["home_team"]["abbreviation"])
        away = norm_team(g["visitor_team"]["abbreviation"])
        hs, vs = g.get("home_team_score") or 0, g.get("visitor_team_score") or 0
        if home not in rec or away not in rec or hs == vs:
            continue
        winner, loser = (home, away) if hs > vs else (away, home)
        rec[winner]["w"] += 1
        rec[loser]["l"] += 1
        d = g.get("date", "")[:10]
        if d and (last_date is None or d > last_date):
            last_date = d
    return rec, last_date


# --------------------------------------------------------------------------- #
# ESPN: cross-check only
# --------------------------------------------------------------------------- #
def _walk_entries(node):
    if isinstance(node, dict):
        if isinstance(node.get("entries"), list):
            yield from node["entries"]
        for v in node.values():
            if isinstance(v, (dict, list)):
                yield from _walk_entries(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_entries(v)


def parse_espn(doc: dict) -> dict[str, dict]:
    out = {}
    for entry in _walk_entries(doc):
        abbr = norm_team((entry.get("team") or {}).get("abbreviation", ""))
        if abbr not in TEAMS or abbr in out:
            continue
        stats = {s.get("name"): s.get("value") for s in entry.get("stats", []) if isinstance(s, dict)}
        if stats.get("wins") is None or stats.get("losses") is None:
            continue
        out[abbr] = {"w": int(stats["wins"]), "l": int(stats["losses"])}
    return out


def fetch_espn(season: int) -> dict[str, dict] | None:
    # ESPN labels seasons by the year they end (2026-27 -> 2027)
    url = f"{ESPN_STANDINGS_URL}?season={season + 1}"
    try:
        return parse_espn(http_json(url, retries=3))
    except Exception as e:  # the check is best-effort; never fail the run over it
        print(f"  ESPN check unavailable: {e}", file=sys.stderr)
        return None


def cross_check(primary: dict, espn: dict | None) -> dict:
    if not espn or len(espn) < len(TEAMS):
        return {"status": "unavailable", "mismatches": []}
    mismatches = [
        {"team": t, "balldontlie": f"{primary[t]['w']}-{primary[t]['l']}",
         "espn": f"{espn[t]['w']}-{espn[t]['l']}"}
        for t in sorted(TEAMS)
        if (primary[t]["w"], primary[t]["l"]) != (espn[t]["w"], espn[t]["l"])
    ]
    return {"status": "mismatch" if mismatches else "match", "mismatches": mismatches}


# --------------------------------------------------------------------------- #
# Pool inputs
# --------------------------------------------------------------------------- #
def _csv_rows(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        lines = [ln for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    return list(csv.DictReader(lines))


def load_lines(path: Path) -> dict[str, float]:
    lines = {}
    for row in _csv_rows(path):
        team = norm_team(row.get("team", ""))
        if team not in TEAMS:
            raise SystemExit(f"lines.csv: unknown team code '{row.get('team')}'")
        lines[team] = float(row["line"])
    missing = sorted(set(TEAMS) - set(lines))
    if missing:
        print(f"  warning: no line set for {', '.join(missing)}", file=sys.stderr)
    return lines


PICK_WORDS = {"O": "over", "OVER": "over", "U": "under", "UNDER": "under"}


def load_picks(path: Path) -> list[dict]:
    people = []
    for row in _csv_rows(path):
        name = (row.pop("name", "") or "").strip()
        if not name:
            continue
        picks = {}
        for col, val in row.items():
            if col is None:
                continue
            team = norm_team(col)
            if team not in TEAMS:
                raise SystemExit(f"picks.csv: unknown team column '{col}'")
            v = (val or "").strip().upper()
            if v:
                if v not in PICK_WORDS:
                    raise SystemExit(f"picks.csv: {name} has '{val}' for {team}; use O or U")
                picks[team] = PICK_WORDS[v]
        people.append({"name": name, "picks": picks})
    return people


# --------------------------------------------------------------------------- #
# Google Form responses (published as CSV from the linked Google Sheet)
# --------------------------------------------------------------------------- #
NICKNAMES = {
    "ATL": "Hawks", "BOS": "Celtics", "BKN": "Nets", "CHA": "Hornets", "CHI": "Bulls",
    "CLE": "Cavaliers", "DAL": "Mavericks", "DEN": "Nuggets", "DET": "Pistons",
    "GSW": "Warriors", "HOU": "Rockets", "IND": "Pacers", "LAC": "Clippers",
    "LAL": "Lakers", "MEM": "Grizzlies", "MIA": "Heat", "MIL": "Bucks",
    "MIN": "Timberwolves", "NOP": "Pelicans", "NYK": "Knicks", "OKC": "Thunder",
    "ORL": "Magic", "PHI": "76ers", "PHX": "Suns", "POR": "Trail Blazers",
    "SAC": "Kings", "SAS": "Spurs", "TOR": "Raptors", "UTA": "Jazz", "WAS": "Wizards",
}
_NUMBER = re.compile(r"(?<![\w.])(\d{1,2}(?:\.\d)?)(?![\w.])")


def team_in_header(header: str) -> str | None:
    """Which team a form question is about, e.g. 'Atlanta Hawks: 41.5 wins' -> ATL.
    Also handles grid questions, whose columns look like 'Picks [Atlanta Hawks]'."""
    h = header.lower()
    found = [abbr for abbr, nick in NICKNAMES.items()
             if re.search(rf"(?<![a-z]){re.escape(nick.lower())}(?![a-z])", h)]
    return found[0] if len(found) == 1 else None


def line_in_header(header: str) -> float | None:
    nums = _NUMBER.findall(header)
    return float(nums[-1]) if nums else None


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "nba-ou-pool/1.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8-sig")
        except urllib.error.URLError as e:
            if attempt == 2:
                raise SystemExit(f"Couldn't download the Google Form responses: {e}") from e
            time.sleep(10)
    return ""


def parse_form_csv(text: str, lines: dict[str, float]) -> tuple[list[dict], list[str], int]:
    """Returns (people, warnings, response_count). Each person's latest response wins."""
    if text.lstrip().startswith("<"):
        raise SystemExit(
            "The PICKS_CSV_URL link returned a web page instead of a CSV file. In the responses "
            "sheet use File > Share > Publish to web, choose the responses tab and "
            "'Comma-separated values (.csv)', and copy that link.")
    rows = list(csv.reader(text.splitlines()))
    if not rows:
        return [], ["The Google Form has no responses yet."], 0
    header, body = rows[0], [r for r in rows[1:] if any(c.strip() for c in r)]
    warnings: list[str] = []

    name_col = next((i for i, h in enumerate(header) if "name" in h.lower() and not team_in_header(h)), None)
    if name_col is None:
        name_col = next((i for i, h in enumerate(header) if "email" in h.lower()), None)
    if name_col is None:
        raise SystemExit("The form needs a question with 'name' in its title (for example 'Your name').")

    team_cols: dict[int, str] = {}
    for i, h in enumerate(header):
        abbr = team_in_header(h)
        if i == name_col or not abbr:
            continue
        if abbr in team_cols.values():
            warnings.append(f"The form has more than one question about the {TEAMS[abbr][0]}; using the first.")
            continue
        team_cols[i] = abbr
        form_line = line_in_header(h)
        if form_line is not None and abbr in lines and form_line != lines[abbr]:
            warnings.append(f"The form shows {form_line} for the {TEAMS[abbr][0]} but lines.csv has "
                            f"{lines[abbr]}. Scoring uses lines.csv.")
    missing = [TEAMS[a][0] for a in sorted(TEAMS) if a not in team_cols.values()]
    if missing:
        warnings.append(f"No form question found for: {', '.join(missing)}.")

    latest: dict[str, dict] = {}
    for r in body:
        name = " ".join((r[name_col] if name_col < len(r) else "").split())
        if not name:
            continue
        picks = {}
        for i, abbr in team_cols.items():
            raw = (r[i] if i < len(r) else "").strip()
            word = raw.split()[0].upper() if raw else ""
            if word in PICK_WORDS:
                picks[abbr] = PICK_WORDS[word]
            elif raw:
                warnings.append(f"{name}'s answer '{raw}' for the {TEAMS[abbr][0]} isn't Over or Under; left blank.")
        latest[name.casefold()] = {"name": name, "picks": picks}  # later rows replace earlier ones
    return list(latest.values()), warnings, len(body)


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
def team_outlook(w: int, l: int, line: float | None, n_games: int) -> dict:
    gp = w + l
    remaining = max(n_games - gp, 0)
    proj = round(w / gp * n_games, 1) if gp else None
    out = {"gp": gp, "remaining": remaining, "proj": proj, "result": None, "lean": None}
    if line is None:
        return out
    max_w = w + remaining
    # A side is settled once it can no longer change.
    if w > line:
        out["result"] = "over"
    elif max_w < line:
        out["result"] = "under"
    elif remaining == 0 and w == line:
        out["result"] = "push"
    if proj is not None:
        out["lean"] = "over" if proj > line else "under" if proj < line else "even"
    return out


def score_pick(pick: str | None, outlook: dict) -> str:
    if not pick:
        return "none"
    if outlook["result"]:
        return "push" if outlook["result"] == "push" else ("won" if outlook["result"] == pick else "lost")
    lean = outlook["lean"]
    if lean is None or lean == "even":
        return "even"
    return "on_pace" if lean == pick else "off_pace"


def build_payload(config, records, last_date, check, lines, people) -> dict:
    n = int(config.get("games_per_team", 82))
    teams = []
    outlooks = {}
    for abbr, (name, conf) in TEAMS.items():
        r = records[abbr]
        o = team_outlook(r["w"], r["l"], lines.get(abbr), n)
        outlooks[abbr] = o
        over_n = sum(1 for p in people if p["picks"].get(abbr) == "over")
        under_n = sum(1 for p in people if p["picks"].get(abbr) == "under")
        teams.append({"abbr": abbr, "name": name, "conf": conf, "w": r["w"], "l": r["l"],
                      "line": lines.get(abbr), **o, "picked_over": over_n, "picked_under": under_n})
    teams.sort(key=lambda t: (-(t["w"] / t["gp"] if t["gp"] else 0), t["l"], t["abbr"]))

    players = []
    for p in people:
        states = {abbr: score_pick(p["picks"].get(abbr), outlooks[abbr]) for abbr in TEAMS}
        won = sum(s == "won" for s in states.values())
        lost = sum(s == "lost" for s in states.values())
        on_pace = sum(s == "on_pace" for s in states.values())
        players.append({
            "name": p["name"],
            "picks": {a: {"pick": p["picks"].get(a), "state": s} for a, s in states.items()},
            "won": won, "lost": lost,
            "pushes": sum(s == "push" for s in states.values()),
            "on_pace": on_pace,
            "projected": won + on_pace,
        })
    players.sort(key=lambda x: (-x["projected"], -x["won"], x["lost"], x["name"].lower()))
    rank = 0
    prev = None
    for i, pl in enumerate(players, 1):
        key = (pl["projected"], pl["won"], pl["lost"])
        if key != prev:
            rank, prev = i, key
        pl["rank"] = rank

    season = int(config["season"])
    return {
        "pool_name": config.get("pool_name", "NBA Over/Under Pool"),
        "demo": bool(config.get("demo", False)),
        "season": season,
        "season_label": f"{season}-{str(season + 1)[-2:]}",
        "games_per_team": n,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "last_game_date": last_date,
        "games_played_total": sum(t["gp"] for t in teams) // 2,
        "check": check,
        "teams": teams,
        "players": players,
    }


# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fixtures", type=Path, help="read bdl_games.json / espn.json from this folder instead of the network")
    ap.add_argument("--season", type=int, help="override config.json season (start year, e.g. 2026 for 2026-27)")
    ap.add_argument("--through", help="test mode: only count games on or before this date (YYYY-MM-DD)")
    ap.add_argument("--form-csv", type=Path, help="test: read Google Form responses from this local CSV file")
    ap.add_argument("--out", type=Path, default=ROOT / "site" / "data" / "pool.json")
    ap.add_argument("--root", type=Path, default=ROOT, help="folder holding config.json, lines.csv, picks.csv")
    args = ap.parse_args()

    config = json.loads((args.root / "config.json").read_text())
    if args.season:
        config["season"] = args.season
    season = int(config["season"])
    lines = load_lines(args.root / "lines.csv")
    form_url = os.environ.get("PICKS_CSV_URL", "").strip()
    warnings: list[str] = []
    if args.form_csv or form_url:
        if args.form_csv:
            text = args.form_csv.read_text(encoding="utf-8-sig")
        else:
            print("Fetching picks from the Google Form responses...")
            text = fetch_text(form_url)
        people, warnings, n_responses = parse_form_csv(text, lines)
        picks_source = f"{len(people)} entries from the Google Form"
        if n_responses > len(people):
            picks_source += f" ({n_responses - len(people)} earlier resubmissions replaced)"
    else:
        people = load_picks(args.root / "picks.csv")
        picks_source = f"{len(people)} entries from picks.csv"
    print(f"  {picks_source}")
    for w in warnings:
        print(f"  note: {w}")

    if args.fixtures:
        games = json.loads((args.fixtures / "bdl_games.json").read_text())
        espn_path = args.fixtures / "espn.json"
        espn = parse_espn(json.loads(espn_path.read_text())) if espn_path.exists() else None
    else:
        key = os.environ.get("BALLDONTLIE_API_KEY", "").strip()
        if not key:
            raise SystemExit("BALLDONTLIE_API_KEY is not set.")
        print(f"Fetching {season}-{str(season + 1)[-2:]} games from balldontlie...")
        games = fetch_bdl_games(season, key)
        print("Fetching ESPN standings for the cross-check...")
        espn = fetch_espn(season)

    test_note = None
    if args.through:
        try:
            dt.date.fromisoformat(args.through)
        except ValueError:
            raise SystemExit(f"--through must be a date like 2026-01-15, not '{args.through}'")
        games = [g for g in games if (g.get("date") or "")[:10] <= args.through]
        espn = None  # ESPN only has current standings, so it can't check a cutoff date
    if args.through or season != int(json.loads((args.root / "config.json").read_text())["season"]):
        label = f"{season}-{str(season + 1)[-2:]}"
        test_note = f"{label} season" + (f" through {args.through}" if args.through else "")

    records, last_date = count_records(games)
    check = cross_check(records, espn)
    if args.through:
        check["status"] = "skipped"
    payload = build_payload(config, records, last_date, check, lines, people)
    payload["test_note"] = test_note
    payload["picks_source"] = picks_source
    payload["warnings"] = warnings[:12]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=1) + "\n")
    print(f"Wrote {args.out.relative_to(ROOT) if args.out.is_relative_to(ROOT) else args.out}: "
          f"{payload['games_played_total']} games, {len(people)} players, ESPN check: {check['status']}")
    for m in check["mismatches"]:
        print(f"  MISMATCH {m['team']}: balldontlie {m['balldontlie']} vs ESPN {m['espn']}")


if __name__ == "__main__":
    main()
