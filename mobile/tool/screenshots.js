#!/usr/bin/env node
// Takes the screenshots the app shops ask for, at the sizes they ask for.
//
//   flutter build web --release --no-web-resources-cdn
//   node tool/screenshots.js            (from mobile/; needs `npm i playwright`)
//
// It runs the web build of the app in a headless browser with a set of quiz
// answers already saved, so what is pictured is the real app drawing real
// data. Output goes to store/.
const { chromium } = require('playwright');
const fs = require('fs');
const http = require('http');
const path = require('path');

const root = path.resolve(__dirname, '..');
const web = path.join(root, 'build', 'web');
const out = path.join(root, 'store', 'screenshots');
const quiz = JSON.parse(fs.readFileSync(path.join(root, 'assets', 'data', 'quiz.json'), 'utf8'));

// Someone part-way through: most of the Commons statements and of the
// Assembly's votes answered, some marked as mattering more, a few skipped; a
// Belfast postcode already looked up, which has an MP and five MLAs.
const scale = [1, 0.5, -0.5, -1, 0.5, 0, 1, -1, 0.5, -0.5];
const answers = {};
quiz.statements.forEach((s, i) => {
  if (i % 9 === 8) return;
  answers[s.id] = { v: scale[i % scale.length], skipped: false, imp: i % 7 === 0 };
});
const ASSEMBLY = 'NI Assembly';
quiz.chambers[ASSEMBLY].statements.forEach((s, i) => {
  if (i % 11 === 10) return;
  answers[s.id] = { v: scale[(i * 3) % scale.length], skipped: false, imp: i % 6 === 0 };
});
const saved = JSON.stringify({
  answers,
  ats: { commons: 6, [ASSEMBLY]: 2 },
  section: 'commons',
  mp: null,
  started: true,
  place: {
    label: 'BT7 1NN',
    keys: ['UK Parliament||Belfast South and Mid Down', `${ASSEMBLY}||Belfast South`],
    notes: [],
    codes: ['N09000003'],
    ward: 'Central',
    district: 'N09000003',
  },
});

// name, viewport and pixel ratio.
const devices = [
  // 1290 x 2796: App Store, 6.9-inch iPhone. Also used in the README.
  { name: 'phone', width: 430, height: 932, ratio: 3 },
  // 1080 x 1920: Google Play (no side may be more than twice the other).
  { name: 'play', width: 360, height: 640, ratio: 3 },
  // 2064 x 2752: App Store, 13-inch iPad.
  { name: 'tablet', width: 1032, height: 1376, ratio: 2 },
];

// Where a panel's label should sit for the panel to start just under the app bar.
const UNDER_BAR = 84;

const types = { '.html': 'text/html', '.js': 'text/javascript', '.json': 'application/json',
  '.wasm': 'application/wasm', '.png': 'image/png', '.ttf': 'font/ttf', '.otf': 'font/otf' };

function serve() {
  const server = http.createServer((request, response) => {
    const name = decodeURIComponent(request.url.split('?')[0]);
    const file = path.join(web, name.endsWith('/') ? name + 'index.html' : name);
    if (!file.startsWith(web) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
      response.writeHead(404).end();
      return;
    }
    response.writeHead(200, { 'content-type': types[path.extname(file)] || 'application/octet-stream' });
    fs.createReadStream(file).pipe(response);
  });
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(server)));
}

(async () => {
  if (!fs.existsSync(path.join(web, 'main.dart.js'))) {
    console.error('Build the web app first: flutter build web --release --no-web-resources-cdn');
    process.exit(1);
  }
  fs.mkdirSync(out, { recursive: true });
  const server = await serve();
  const url = `http://127.0.0.1:${server.address().port}/`;
  const browser = await chromium.launch();

  for (const d of devices) {
    const context = await browser.newContext({
      viewport: { width: d.width, height: d.height },
      deviceScaleFactor: d.ratio,
      colorScheme: 'light',
    });
    // shared_preferences on the web keeps each value JSON-encoded under "flutter.<key>".
    await context.addInitScript((value) => {
      localStorage.setItem('flutter.glasshouse.quiz.v1', JSON.stringify(value));
    }, saved);
    const page = await context.newPage();
    await page.goto(url, { waitUntil: 'networkidle' });
    await page.waitForTimeout(3500);

    const shot = async (label) => {
      // A phone has no pointer. Park it on the title bar, where nothing
      // lights up under it, before the picture is taken.
      await page.mouse.move(d.width / 2, 20);
      await page.waitForTimeout(900);
      await page.screenshot({ path: path.join(out, `${d.name}-${label}.png`) });
    };
    // The four destinations share the width of the bar at the bottom.
    const tab = async (index) => {
      await page.mouse.click((d.width / 4) * (index + 0.5), d.height - 34);
      // A pointer left resting on the bar brings up its tooltip, which a
      // phone never shows. Move it away and let the tooltip go.
      await page.mouse.move(d.width / 2, 20);
      await page.waitForTimeout(1600);
    };

    // The app draws on a canvas, so there is nothing in the page to scroll to.
    // Switching on its accessibility tree gives every piece of text a position,
    // which is enough to steer by.
    await page.evaluate(() => {
      const find = (node) => {
        const hit = node.querySelector('flt-semantics-placeholder');
        if (hit) return hit;
        for (const child of node.querySelectorAll('*')) {
          const inner = child.shadowRoot && find(child.shadowRoot);
          if (inner) return inner;
        }
        return null;
      };
      const button = find(document);
      if (button) button.click();
    });
    await page.waitForTimeout(800);
    const topOf = async (text) => {
      const found = page.getByText(text).first();
      if ((await found.count()) === 0) return null;
      const box = await found.boundingBox();
      return box ? box.y : null;
    };
    const wheel = async (delta) => {
      await page.mouse.move(d.width / 2, d.height / 2);
      await page.mouse.wheel(0, delta);
      await page.waitForTimeout(350);
    };
    // How far the page moves for a wheel turn differs between browsers and
    // pixel ratios, so it is measured rather than assumed.
    const measure = async (text) => {
      const before = await topOf(text);
      await wheel(60);
      const after = await topOf(text);
      const moved = before !== null && after !== null ? (before - after) / 60 : 0;
      return moved > 0.01 ? moved : 1;
    };
    // Scrolls until the given text is `at` pixels from the top of the screen.
    const bring = async (text, at, perUnit) => {
      for (let i = 0; i < 80; i++) {
        const y = await topOf(text);
        const off = y === null ? 300 : y - at;       // not on screen yet: keep going down
        if (y !== null && Math.abs(off) < 1.5) return;
        await wheel(off / perUnit);
      }
      throw new Error(`could not scroll to "${text}"`);
    };

    await shot('1-representatives');
    await tab(1);
    await shot('2-quiz');
    await tab(2);
    // Everyone who represents you, in both parliaments, each with a figure.
    await shot('3-match');
    const perUnit = await measure('Based on the');
    await bring('Where the votes sit', UNDER_BAR, perUnit);
    await shot('4-compass');
    await bring('Statement by statement', UNDER_BAR, perUnit);
    await shot('5-statements');
    await bring('Vote by vote', UNDER_BAR, perUnit);
    await shot('6-votes');
    await context.close();
    console.log(`${d.name}: ${d.width * d.ratio} x ${d.height * d.ratio}`);
  }

  await browser.close();
  server.close();
})();
