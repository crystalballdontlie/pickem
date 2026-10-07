/**
 * Builds the pool's Google Form: one "Your name" question plus an Over/Under
 * question for every team, and a linked Google Sheet that collects responses.
 *
 * How to use (about 2 minutes):
 *   1. Go to https://script.google.com and click "New project".
 *   2. Delete the sample code, paste this whole file in, and click Save.
 *   3. Edit POOL_NAME and the LINES below (keep them identical to lines.csv).
 *   4. Choose createPoolForm in the function menu and click Run.
 *      Google asks you to authorize it the first time; allow it.
 *   5. Open View > Logs (or the Execution log). It prints three links:
 *      the form to send to your friends, the form editor, and the responses sheet.
 *
 * Question titles look like "Atlanta Hawks: 41.5 wins". The nightly update
 * finds each team by name in the title, so you can reword the rest of the
 * title, but keep the team name in it.
 */

const POOL_NAME = 'NBA Over/Under Pool 2026-27';

// Replace every 41.5 with your pool's line. Keep these identical to lines.csv.
const LINES = [
  ['Atlanta Hawks', 41.5],
  ['Boston Celtics', 41.5],
  ['Brooklyn Nets', 41.5],
  ['Charlotte Hornets', 41.5],
  ['Chicago Bulls', 41.5],
  ['Cleveland Cavaliers', 41.5],
  ['Dallas Mavericks', 41.5],
  ['Denver Nuggets', 41.5],
  ['Detroit Pistons', 41.5],
  ['Golden State Warriors', 41.5],
  ['Houston Rockets', 41.5],
  ['Indiana Pacers', 41.5],
  ['LA Clippers', 41.5],
  ['Los Angeles Lakers', 41.5],
  ['Memphis Grizzlies', 41.5],
  ['Miami Heat', 41.5],
  ['Milwaukee Bucks', 41.5],
  ['Minnesota Timberwolves', 41.5],
  ['New Orleans Pelicans', 41.5],
  ['New York Knicks', 41.5],
  ['Oklahoma City Thunder', 41.5],
  ['Orlando Magic', 41.5],
  ['Philadelphia 76ers', 41.5],
  ['Phoenix Suns', 41.5],
  ['Portland Trail Blazers', 41.5],
  ['Sacramento Kings', 41.5],
  ['San Antonio Spurs', 41.5],
  ['Toronto Raptors', 41.5],
  ['Utah Jazz', 41.5],
  ['Washington Wizards', 41.5],
];

function createPoolForm() {
  if (LINES.length !== 30) throw new Error('LINES should list all 30 teams; it has ' + LINES.length);

  const form = FormApp.create(POOL_NAME);
  form.setDescription(
    'Pick over or under on each team\'s regular-season win total. ' +
    'If you submit more than once, your latest entry counts, as long as you use the same name. ' +
    'Picks close at tip-off of the first game.');
  form.setCollectEmail(false);
  form.setProgressBar(true);
  form.setConfirmationMessage('Picks saved. They will show on the pool site after the next nightly update.');

  form.addTextItem()
    .setTitle('Your name')
    .setHelpText('This is how you will appear on the leaderboard. Use the same name if you resubmit.')
    .setRequired(true);

  LINES.forEach(function (row) {
    form.addMultipleChoiceItem()
      .setTitle(row[0] + ': ' + row[1] + ' wins')
      .setChoiceValues(['Over', 'Under'])
      .setRequired(true);
  });

  const sheet = SpreadsheetApp.create(POOL_NAME + ' (responses)');
  form.setDestination(FormApp.DestinationType.SPREADSHEET, sheet.getId());

  // Newer Google Forms start unpublished; publish so friends can open the link.
  if (typeof form.setPublished === 'function') form.setPublished(true);

  Logger.log('Send this link to everyone:  ' + form.getPublishedUrl());
  Logger.log('Edit the form:                ' + form.getEditUrl());
  Logger.log('Responses sheet:              ' + sheet.getUrl());
}
