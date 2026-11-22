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

// Someone part-way through: most statements answered, some marked as
// mattering more, a few skipped; a Glasgow postcode already looked up.
const scale = [1, 0.5, -0.5, -1, 0.5, 0, 1, -1, 0.5, -0.5];
const answers = {};
quiz.statements.forEach((s, i) => {
  if (i % 9 === 8) return;
  answers[s.id] = { v: scale[i % scale.length], skipped: false, imp: i % 7 === 0 };
});
const saved = JSON.stringify({
  answers,
  at: 6,
  mp: null,
  started: true,
  place: {
    label: 'G12 8QQ',
    keys: [
      'UK Parliament||Glasgow North',
      'Scottish Parliament||Glasgow Kelvin and Maryhill',
      'Scottish Parliament||Glasgow',
    ],
    notes: [],
  },
});

// name, viewport, pixel ratio, and how far to scroll for the two lower shots.
const devices = [
  // 1290 x 2796: App Store, 6.9-inch iPhone. Also used in the README.
  { name: 'phone', width: 430, height: 932, ratio: 3, compass: 470, statements: 2040 },
  // 1080 x 1920: Google Play (no side may be more than twice the other).
  { name: 'play', width: 360, height: 640, ratio: 3, compass: 560, statements: 2060 },
  // 2064 x 2752: App Store, 13-inch iPad.
  { name: 'tablet', width: 1032, height: 1376, ratio: 2, compass: 300, statements: 1560 },
];

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
      await page.waitForTimeout(800);
      await page.screenshot({ path: path.join(out, `${d.name}-${label}.png`) });
    };
    // The four destinations share the width of the bar at the bottom.
    const tab = async (index) => {
      await page.mouse.click((d.width / 4) * (index + 0.5), d.height - 34);
      await page.waitForTimeout(700);
    };
    const scrollTo = async (y) => {
      await page.mouse.move(d.width / 2, d.height / 2);
      await page.mouse.wheel(0, y);
      await page.waitForTimeout(600);
    };

    await shot('1-representatives');
    await tab(1);
    await shot('2-quiz');
    await tab(2);
    await shot('3-match');
    await scrollTo(d.compass);
    await shot('4-compass');
    await scrollTo(d.statements - d.compass);
    await shot('5-statements');
    await context.close();
    console.log(`${d.name}: ${d.width * d.ratio} x ${d.height * d.ratio}`);
  }

  await browser.close();
  server.close();
})();
