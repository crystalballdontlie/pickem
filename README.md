# NBA Over/Under Pool

A website for a friendly NBA win-total pool. Friends submit their picks through a Google
Form. Every night around midnight Pacific, a GitHub Action pulls the day's final scores,
updates every team's record, scores everyone's picks against the lines and republishes
the site. Nothing to host and nothing to pay for.

## How it works

```
Google Form ──► responses Google Sheet ──(published CSV link)──┐
                                                               ▼
GitHub Actions, ≈12:15 AM Pacific ──► scripts/update.py
       ├─ balldontlie /v1/games   counts wins and losses from final games   (primary source)
       ├─ ESPN standings          compares every team's record              (cross-check)
       ├─ lines.csv               the win-total line for each team
       ├─ form responses          each person's Over/Under picks
       └─ writes site/data/pool.json
  └─ commits pool.json and publishes site/ on GitHub Pages ──► your pool's website
```

- **Records** come from counting final regular-season games on balldontlie's free tier.
  NBA Cup group and knockout games count. The Cup championship game doesn't count (it isn't
  part of the 82-game record), and playoff and play-in games are excluded.
- **Cross-check**: if ESPN's standings disagree for any team, the page shows a notice
  naming the teams and both records. The page still shows balldontlie's numbers.
  If ESPN can't be reached, the page says the check was unavailable and nothing else changes.
- **Picks** are read from the form's response sheet every night. If someone submits more
  than once under the same name, their latest entry counts (capitals and extra spaces are
  ignored). If no form is connected, picks come from `picks.csv` in the repository instead.
- **Scoring** for each person and team:
  - **Won / Lost** (locked): the over is locked once wins pass the line, and the under is
    locked once the team can no longer reach the line. Whole-number lines can push.
  - **On pace / Off pace**: for open picks, compares the line to the team's current pace
    (wins ÷ games played × 82).
  - **Projected** = locked wins + open picks that are on pace. The leaderboard ranks by
    projected, then by locked wins.
  - **Clinch in** on the Teams tab shows how many more wins lock the over and how many
    more losses lock the under.

## What's in this folder

| Path | What it is |
| --- | --- |
| `site/index.html` | The website: leaderboard and team table. |
| `site/data/pool.json` | The data the website shows, rewritten every night. |
| `scripts/update.py` | The nightly job: fetches results and picks, scores, writes `pool.json`. |
| `.github/workflows/nightly.yml` | Runs the nightly job on GitHub and publishes the site. |
| `google-form/create_form.gs` | A script that builds the Google Form for you. |
| `lines.csv` | The line for each team. **Scoring always uses this file.** |
| `picks.csv` | Backup picks, used only when no Google Form is connected. |
| `config.json` | Pool name and season. |
| `tests/` | Offline tests and sample data. |

## Setup

### 1. GitHub and the nightly job (about 10 minutes)

1. **Get a free balldontlie API key** at <https://app.balldontlie.io>.
2. **Create a GitHub repository** and upload this folder to it (branch `main`). The
   easiest way is *Add file → Upload files* on the new repo page, then drag in the
   *contents* of this folder. GitHub Pages is free for public repositories; a private
   repository needs a paid GitHub plan to use Pages.
   - The upload page may skip the hidden `.github` folder. If the Actions tab shows no
     workflow afterwards, create `.github/workflows/nightly.yml` with *Add file → Create
     new file* and paste in the contents of that file.
3. **Add the API key as a secret**: *Settings → Secrets and variables → Actions → New
   repository secret*. Name: `BALLDONTLIE_API_KEY`. Value: your key.
4. **Turn on Pages**: *Settings → Pages → Build and deployment → Source:* **GitHub Actions**.
5. **Run it once**: *Actions → Nightly standings update → Run workflow*. It takes about
   four minutes, because the free tier allows 5 requests a minute. Your site's address
   appears on the finished run's summary page (usually `https://<you>.github.io/<repo>/`).

### 2. The Google Form (about 10 minutes)

1. **Set your lines** in `google-form/create_form.gs` and in `lines.csv`. Use the same
   numbers in both. The form shows them to your friends; `lines.csv` is what scores them.
2. **Build the form**: open <https://script.google.com>, click *New project*, paste in all
   of `create_form.gs`, save, choose `createPoolForm` and click *Run*. Allow the
   permissions it asks for. The execution log prints three links: the form to send out,
   the form editor and the responses sheet.
   - Prefer to build the form yourself? That works too. Include a question with "name" in
     its title, and one Over/Under question per team with the team's name in the title
     (for example "Boston Celtics: 52.5 wins"). A multiple-choice grid with teams as rows
     also works.
3. **Publish the responses as a CSV link**: in the responses sheet, *File → Share →
   Publish to web*. Choose the responses tab (usually "Form Responses 1") and
   *Comma-separated values (.csv)*, then *Publish*. Copy the link.
4. **Add that link as a second secret** named `PICKS_CSV_URL`.

About privacy: anyone who has the CSV link can read the responses, so keep it in the
secret and don't post it. The pool website shows everyone's names and picks anyway. The
form is set not to collect email addresses, so none end up in the sheet.

## Testing before the season starts

Try these in order. Each test builds on the one before.

**A. Last season's results with sample picks.** This tests the GitHub setup and the API key.

1. Put last season's real lines in `lines.csv` (if you have them) so the results mean something.
2. In `picks.csv`, add two or three made-up rows (remove the `#` from the example row).
3. *Actions → Nightly standings update → Run workflow*. Set **season** to `2025` (that's
   2025-26; balldontlie labels seasons by the year they start) and leave **through** blank.
4. Open the site. You should see last season's final records, every pick settled as won
   or lost, a banner saying it's a test run and, after a full season, "Verified against
   ESPN". Spot-check a team or two: if a line was 48.5 and the team went 50-32, an over
   pick shows as won.
5. Run it again with **through** set to `2026-01-15` to see a mid-season snapshot, with
   picks on or off pace. The ESPN check is skipped with a cutoff date, because ESPN only
   reports current standings.

**B. The Google Form.** This tests the connection to your form.

1. After setting up the form and the `PICKS_CSV_URL` secret, submit the form two or three
   times yourself under different names. Submit once more under one of those names with
   different answers to check that the latest entry replaces the earlier one.
2. Run the workflow again with **season** `2025`. The header should say "N entries from the
   Google Form". Any problems with the form (a team the update couldn't find, a line in the
   form that doesn't match `lines.csv`) appear in a "Picks setup" note at the top of the page.

**C. Clean up before sending the form out.** Delete your test rows from the responses
sheet. Removing responses inside Google Forms doesn't remove them from the sheet. Then run
the workflow with both boxes blank. The site goes back to the 2026-27 season with your
real pool's entries.

Test runs don't change anything permanent: the next scheduled run or a normal run goes back
to the live season and clears the test banner.

## During the season

- **Close the form at tip-off**: in the form, *Responses → Accepting responses* off. The
  update doesn't enforce a deadline, so a late resubmission would count if the form were
  still open.
- **Late entries or corrections**: edit the row in the responses sheet; it's picked up at
  the next update. To refresh immediately, use *Run workflow* with both boxes blank.
- **Editing files on GitHub** (`lines.csv`, `config.json`) rebuilds the site within a few minutes.
- **Timing**: GitHub sometimes starts scheduled runs 10–30 minutes late, so expect each
  update between about 12:15 and 1:00 AM Pacific. The schedule covers both daylight and
  standard time.

## If something goes wrong

- **The run fails with a 401**: the `BALLDONTLIE_API_KEY` secret is missing or wrong.
- **The run fails saying the link "returned a web page instead of a CSV file"**: the
  `PICKS_CSV_URL` secret is the sheet's normal link. Use the *Publish to web* CSV link.
- **The run fails saying the form needs a "name" question**: the update finds the name
  question by the word "name" in its title.
- **GitHub emails you that a run failed**: the site keeps showing the last good data, and
  the next night's run usually recovers on its own.
- **After a quiet summer**: GitHub turns off scheduled workflows in repositories with no
  activity for 60 days. Before the next season, check the Actions tab and click *Enable
  workflow* if prompted.
- **A new season**: bump `season` in `config.json`, update `lines.csv`, and build a new form.

## Running locally (optional)

```bash
BALLDONTLIE_API_KEY=your-key python scripts/update.py          # real data
python tests/make_fixtures.py && python tests/test_update.py   # offline tests
python -m http.server -d site 8000                            # view at localhost:8000
python scripts/update.py --form-csv responses.csv ...         # use a downloaded form export
```
