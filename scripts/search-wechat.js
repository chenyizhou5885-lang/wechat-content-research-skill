#!/usr/bin/env node

const path = require("path");
const { spawnSync } = require("child_process");

function usage() {
  console.error("Usage: node scripts/search-wechat.js <query> [-n number] [--days number] [-r]");
}

const argv = process.argv.slice(2);
let query = "";
let requested = 10;
let days = 365;
let resolveUrl = false;

for (let i = 0; i < argv.length; i += 1) {
  const value = argv[i];
  if (value === "-n" || value === "--num") {
    requested = Number.parseInt(argv[i + 1], 10);
    i += 1;
  } else if (value === "--days") {
    days = Number.parseInt(argv[i + 1], 10);
    i += 1;
  } else if (value === "-r" || value === "--resolve-url") {
    resolveUrl = true;
  } else if (!value.startsWith("-") && !query) {
    query = value;
  }
}

if (!query || !Number.isFinite(requested) || requested < 1 || !Number.isFinite(days) || days < 1) {
  usage();
  process.exit(2);
}

requested = Math.min(requested, 50);
// Resolving links sends extra requests. Keep that path deliberately small to
// reduce latency and the chance of triggering Sogou's anti-bot controls.
const fetchCount = resolveUrl
  ? requested
  : Math.min(50, Math.max(requested, requested * 3));
const bundle = path.join(__dirname, "wechat-search.bundle.cjs");
const childArgs = [bundle, query, "-n", String(fetchCount)];
if (resolveUrl) childArgs.push("-r");

const result = spawnSync(process.execPath, childArgs, {
  encoding: "utf8",
  maxBuffer: 20 * 1024 * 1024,
});

if (result.stderr) process.stderr.write(result.stderr);
if (result.error) {
  console.error(JSON.stringify({ ok: false, error: result.error.message }));
  process.exit(1);
}
if (result.status !== 0) {
  if (result.stdout) process.stdout.write(result.stdout);
  process.exit(result.status || 1);
}

let payload;
try {
  const jsonStart = result.stdout.indexOf("{");
  payload = JSON.parse(jsonStart >= 0 ? result.stdout.slice(jsonStart) : result.stdout);
} catch (error) {
  console.error(JSON.stringify({ ok: false, error: `Invalid search output: ${error.message}` }));
  process.exit(1);
}

const now = new Date();
const cutoff = new Date(now.getTime() - days * 24 * 60 * 60 * 1000);
const dated = [];
const undated = [];
let excludedOutsideWindowOrInvalidDate = 0;

for (const article of payload.articles || []) {
  if (!article.datetime) {
    undated.push(article);
    continue;
  }
  const publishedAt = new Date(`${article.datetime.replace(" ", "T")}+08:00`);
  if (!Number.isNaN(publishedAt.getTime()) && publishedAt >= cutoff && publishedAt <= now) {
    dated.push({ ...article, published_at: publishedAt.toISOString() });
  } else {
    excludedOutsideWindowOrInvalidDate += 1;
  }
}

dated.sort((a, b) => b.published_at.localeCompare(a.published_at));
const articles = dated.slice(0, requested);

process.stdout.write(`${JSON.stringify({
  ok: true,
  channel: "sogou-weixin",
  query,
  requested,
  returned: articles.length,
  date_from: cutoff.toISOString(),
  date_to: now.toISOString(),
  excluded_outside_window_or_invalid_date: excludedOutsideWindowOrInvalidDate,
  excluded_missing_date: undated.length,
  articles,
}, null, 2)}\n`);
