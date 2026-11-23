#!/usr/bin/env node
// Opens the website in a real browser, uses it the way a person would, and
// compares what it shows with the reference arithmetic.
//
//   python app/check/reference.py > want.json
//   node app/check/check.js app want.json [folder for screenshots]
//
// Needs Node and Playwright (npm install playwright). It serves the folder
// itself and stands in for postcodes.io, so nothing leaves the machine.
const { chromium } = require('playwright');
const fs = require('fs');
const http = require('http');
const path = require('path');

const [app, wantFile, shots] = process.argv.slice(2);
if (!app || !wantFile) {
  console.error('usage: node app/check/check.js <folder with index.html> <want.json> [screenshots folder]');
  process.exit(2);
}
const want = JSON.parse(fs.readFileSync(wantFile, 'utf8'));
const STORE = 'glasshouse.quiz.v1';
const types = { '.html': 'text/html; charset=utf-8', '.json': 'application/json' };
const server = http.createServer((request, response) => {
  const name = decodeURIComponent(request.url.split('?')[0]);
  const file = path.join(app, name === '/' ? 'index.html' : name);
  if (!file.startsWith(path.resolve(app)) && !file.startsWith(app)) { response.writeHead(403).end(); return; }
  if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) { response.writeHead(404).end(); return; }
  response.writeHead(200, { 'content-type': types[path.extname(file)] || 'application/octet-stream' });
  fs.createReadStream(file).pipe(response);
});

let failures = 0;
const ok = (passed, what) => {
  if (!passed) failures++;
  console.log((passed ? '  ok   ' : '  FAIL ') + what);
};
const upper = (s) => s.toUpperCase();

(async () => {
  await new Promise((done) => server.listen(0, '127.0.0.1', done));
  const url = `http://127.0.0.1:${server.address().port}/`;
  const browser = await chromium.launch();
  const errors = [];
  const pc = want.postcode.postcode.replace(/\s+/g, '');

  const context = async (viewport, phone) => {
    // A phone's browser honours the page's viewport tag; a narrow desktop
    // window does not need one. Only the first shows what a phone will show.
    const ctx = await browser.newContext(phone
      ? { viewport, isMobile: true, hasTouch: true, deviceScaleFactor: 2 }
      : { viewport });
    // postcodes.io, as far as the page can tell; and no typefaces from the network
    await ctx.route('https://api.postcodes.io/**', (route) =>
      route.request().url().endsWith('/postcodes/' + pc)
        ? route.fulfill({ json: { status: 200, result: want.postcode } })
        : route.fulfill({ status: 404, json: { status: 404 } }));
    await ctx.route('https://fonts.googleapis.com/**', (route) =>
      route.fulfill({ status: 200, contentType: 'text/css', body: '' }));
    return ctx;
  };
  // A change of hash alone does not reload the page, and what was saved is
  // only read when it loads: go by way of a blank page.
  const open = async (page, view) => {
    await page.goto('about:blank');
    await page.goto(url + '#' + view, { waitUntil: 'networkidle' });
  };
  const shot = async (page, name) => {
    if (shots) await page.screenshot({ path: path.join(shots, name + '.png'), fullPage: true });
  };

  const page = await (await context({ width: 1180, height: 900 })).newPage();
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => {
    if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push(m.text());
  });
  await open(page, 'reps');

  // ---- an example first, and nothing local claimed for it
  ok(upper(await page.locator('#place .eyebrow').first().innerText()) === 'AN EXAMPLE — SEARCH ABOVE FOR YOURS',
    'opens on a labelled example');
  ok(await page.getByText('Elections coming up here').count() === 0, 'claims nothing local for the example');

  // ---- a postcode: an MP and several devolved members, elections, councillors
  const names = Object.keys(want.reps);
  const d = want.devolved;
  await page.fill('#place-search', want.postcode.postcode);
  await page.press('#place-search', 'Enter');
  await page.waitForSelector('#place .card');
  const cards = await page.locator('#place .chamber .card .cname').allInnerTexts();
  ok(names.every((n) => cards.includes(n)), `the MP and every ${d.role} are listed: ${cards.join(', ')}`);
  ok(await page.getByText(`Your ${d.role}s are matched on the ${d.house}'s own votes`).count() === 1,
    `says the ${d.house} has questions of its own`);
  ok(await page.getByText('Elections coming up here').count() === 1, 'has an elections section');
  ok(await page.getByText('Your councillors').count() === 1, 'has a councillors section');
  const council = await page.locator('#place .chamber').last().innerText();
  ok(council.includes(want.council.ward) && council.includes(`${want.council.within} ward is part of`)
    && /Meetings attended/.test(council) && /There is no match with your answers/.test(council),
    `councillors for ${want.council.within}, in ${want.council.ward}, with attendance and no match`);
  await shot(page, 'web-reps');

  // ---- the quiz, in parts
  await page.getByRole('button', { name: `Answer the ${d.house} questions` }).click();
  await page.waitForSelector('#quiz-card:not([hidden])');
  ok(upper(await page.locator('#q-count').innerText()) === `VOTE 1 OF ${d.count}`, `opens the ${d.house} part at vote 1`);
  ok(await page.locator('#q-lead').innerText() === 'I would have voted for…', 'asks how you would have voted');
  await page.locator('#q-more summary').click();
  ok(/One vote, on \d+ \w+ \d{4}: \d+ for, \d+ against/.test(await page.locator('#q-detail').innerText()),
    'shows the vote and its result');
  await page.locator('#q-leave').click();
  const parts = await page.locator('#parts .part .cname').allInnerTexts();
  ok(parts[0] === 'House of Commons' && parts[1] === d.house && parts[2] === 'Earlier parliaments',
    'offers the parts, yours first: ' + parts.join(' | '));
  ok(await page.locator('#parts .part .role').first().innerText() === `Your ${d.role}s`, 'marks the part that is yours');
  await shot(page, 'web-parts');

  await page.locator('#parts .part').first().getByRole('button').click();
  ok(upper(await page.locator('#q-count').innerText()) === `STATEMENT 1 OF ${want.coreCount}`,
    'the Commons part asks about this parliament only');
  ok(await page.locator('#q-done').isDisabled(), 'no match before five answers');
  for (const key of ['1', '2', '3', '4', '5']) {
    await page.keyboard.press(key);
    await page.waitForTimeout(260);
  }
  ok(!(await page.locator('#q-done').isDisabled()), 'five answers unlock it');
  ok(upper(await page.locator('#q-count').innerText()) === `STATEMENT 6 OF ${want.coreCount}`, 'and it moved on by itself');

  // ---- the answers the reference used, and every figure compared
  await page.evaluate(([key, saved]) => localStorage.setItem(key, JSON.stringify(saved)), [STORE, want.saved]);
  await open(page, 'match');
  await page.waitForSelector('#match-body .panel');
  const rows = await page.locator('#match-body .repgroup .rank li').evaluateAll((items) => items.map((li) => ({
    name: li.querySelector('button').textContent,
    sub: li.querySelector('.sub').textContent,
    v: li.querySelector('.v').textContent,
  })));
  for (const [name, w] of Object.entries(want.reps)) {
    const got = rows.find((r) => r.name === name);
    ok(!!got && got.v === w.v && got.sub.endsWith(w.basis),
      `${name}: ${got ? got.v + ' · ' + got.sub : 'missing'}   (reference: ${w.v} · ${w.basis})`);
  }
  const eyebrows = (await page.locator('#match-body .hero .eyebrow').allInnerTexts()).map(upper);
  ok(eyebrows.includes('YOUR MP') && eyebrows.includes(`YOUR ${upper(d.role)}`),
    'each parliament\'s results are about your own member: ' + eyebrows.join(', '));
  if (Object.values(want.reps).some((w) => /they could have$/.test(w.basis))) {
    ok(await page.getByText('so this is a partial picture').count() >= 1, 'a partial record is shown, and called partial');
  }
  const blocks = await page.locator('#match-body .block').evaluateAll((all) => all.map((b) => ({
    id: b.id,
    top: [...b.querySelectorAll('ol.rank li')].map((li) =>
      li.querySelector('button').textContent + ' ' + li.querySelector('.v').textContent),
  })));
  for (const [id, top] of Object.entries(want.top)) {
    const got = (blocks.find((b) => b.id === id) || { top: [] }).top;
    ok(JSON.stringify(got) === JSON.stringify(top), `the six closest in ${id}: ${got.join(', ')}`);
  }
  await shot(page, 'web-match');

  // picking another member from the summary makes that parliament's results about them
  const block = '#' + d.block;
  await page.locator('#match-body .repgroup').nth(1).getByRole('button', { name: d.other }).click();
  ok((await page.locator(block + ' .hero').innerText()).includes(d.other), `its results follow the ${d.role} you pick`);
  ok(await page.locator(block + ' .cmp').count() === d.answered, `one row for each of your ${d.answered} answers`);
  await page.locator(block + ' .cmp summary').first().click();
  ok(/^https:\/\//.test(await page.locator(block + ' .cmp[open] .receipts a').first().getAttribute('href')),
    'each row opens onto the legislature\'s own record of the vote');

  // a member's own card carries the match and leads to their results
  await open(page, 'reps');
  const card = page.locator('#place .card', { hasText: d.other });
  ok((await card.locator('.matchbtn').innerText()).startsWith(want.reps[d.other].v + ' match'), `the card of one ${d.role} carries their match`);
  await card.locator('.matchbtn').click();
  await page.waitForSelector(block);
  ok((await page.locator(block + ' .hero').innerText()).includes(d.other), 'and leads to their results');

  // ---- people who hold no seat
  await open(page, 'reps');
  await page.fill('#place-search', want.former.name);
  const first = page.locator('#people-hits .hit').first();
  ok(await first.innerText().then((t) => t.includes(want.former.name) && /Former MP/.test(t)), 'a former MP is found by name');
  await first.click();
  const former = await page.locator('#opened').innerText();
  ok(/No longer sits in the House of Commons/.test(former) && former.includes(want.former.years)
    && !/chamber median/.test(former) && !/questions & speeches/.test(former),
    'and shown by what they did, not measured against today\'s chamber');
  await page.fill('#place-search', want.peer.name);
  await page.locator('#people-hits .hit').first().click();
  const peer = await page.locator('#opened').innerText();
  ok(/Nobody votes for a member of the House of Lords/.test(peer) && /With their group/.test(peer) && !/With their party/.test(peer),
    'a crossbench peer is not described as elected or whipped');
  if (want.candidate) {
    await page.fill('#place-search', want.candidate.name);
    ok(await page.locator('#people-hits .hit').first().innerText().then((t) => /Candidate/.test(t)), 'a candidate is found by name');
    await page.locator('#people-hits .hit').first().click();
    const ballot = await page.locator('#opened').innerText();
    ok(ballot.includes(want.candidate.where) && /Nobody here is scored for standing/.test(ballot) && /Democracy Club/.test(ballot)
      && !/% match/.test(ballot), 'and shown on their ballot, unscored, with the source');
  }
  await page.getByRole('button', { name: 'Close' }).click();
  ok(await page.locator('#opened').isHidden(), 'what was opened can be closed');
  await page.fill('#place-search', 'G12 8');
  ok(await page.locator('#search-msg').innerText() === 'Type the whole postcode, then press Enter.', 'half a postcode is not searched for as a name');

  // ---- How it works carries the real numbers
  await open(page, 'method');
  const method = await page.locator('#v-method').innerText();
  for (const said of want.method) ok(method.includes(said), 'How it works says: ' + said);

  // ---- a save from before there were parts still opens where it was
  await page.evaluate(([key, old]) => localStorage.setItem(key, JSON.stringify(old)), [STORE, want.legacy]);
  await open(page, 'quiz');
  ok(upper(await page.locator('#q-count').innerText()) === `STATEMENT 4 OF ${want.coreCount}`, 'an older save resumes in the Commons part');

  // ---- on a phone: laid out at the phone's own width, and nothing wider
  const PHONE = 390;
  const small = await (await context({ width: PHONE, height: 844 }, true)).newPage();
  small.on('pageerror', (e) => errors.push('phone: ' + e));
  await open(small, 'reps');
  ok(await small.evaluate(() => document.documentElement.clientWidth) === PHONE,
    'a phone lays the page out at its own width, not as a shrunken desktop page');
  await small.evaluate(([key, saved]) => localStorage.setItem(key, JSON.stringify(saved)), [STORE, want.saved]);
  for (const view of ['reps', 'quiz', 'match', 'method']) {
    await open(small, view);
    await small.waitForTimeout(150);
    const over = await small.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    ok(over <= 0, `fits a phone without scrolling sideways: ${view}`);
    await shot(small, 'web-phone-' + view);
  }

  ok(errors.length === 0, 'no script errors' + (errors.length ? ': ' + errors.slice(0, 3).join(' | ') : ''));
  await browser.close();
  server.close();
  console.log(failures ? `${failures} failed` : 'All as the reference says.');
  process.exit(failures ? 1 : 0);
})().catch((e) => {
  console.error(e);
  process.exit(2);
});
