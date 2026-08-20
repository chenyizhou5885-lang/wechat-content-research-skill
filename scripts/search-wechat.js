#!/usr/bin/env node

const path = require("path");
const os = require("os");
const fs = require("fs");
const { spawnSync } = require("child_process");

function usage() {
  console.error("Usage: node scripts/search-wechat.js <query> [-n number] [--days number] [-r|--verify-browser]");
}

const WEBBRIDGE_ENDPOINT = "http://127.0.0.1:10086/command";

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function normalizeText(value) {
  return String(value || "").normalize("NFKC").toLowerCase()
    .replace(/[^\p{Letter}\p{Number}]+/gu, "");
}

function dateKey(value) {
  if (!value) return "";
  const raw = String(value).trim();
  const match = raw.match(/(20\d{2})\D{1,3}(\d{1,2})\D{1,3}(\d{1,2})/);
  if (match) return `${match[1]}-${match[2].padStart(2, "0")}-${match[3].padStart(2, "0")}`;
  const timestamp = /^\d{10}$/.test(raw) ? Number(raw) * 1000 : Date.parse(raw);
  if (Number.isNaN(timestamp)) return "";
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(new Date(timestamp));
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function canonicalizeWechatUrl(rawUrl) {
  const parsed = new URL(rawUrl);
  if (/^\/s\/[A-Za-z0-9_-]+$/.test(parsed.pathname)) {
    parsed.search = "";
    parsed.hash = "";
    return parsed.toString();
  }
  const stable = new URLSearchParams();
  for (const key of ["__biz", "mid", "idx", "sn"]) {
    if (parsed.searchParams.has(key)) stable.set(key, parsed.searchParams.get(key));
  }
  if (!["__biz", "mid", "idx", "sn"].every((key) => stable.has(key))) return null;
  parsed.search = stable.toString();
  parsed.hash = "";
  return parsed.toString();
}

async function webbridge(action, args, session) {
  const response = await fetch(WEBBRIDGE_ENDPOINT, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ action, args, session }),
  });
  if (!response.ok) throw new Error(`WebBridge HTTP ${response.status}`);
  const payload = await response.json();
  if (payload && payload.ok === false) {
    throw new Error(payload.error || `${action} failed`);
  }
  const data = payload && Object.prototype.hasOwnProperty.call(payload, "data") ? payload.data : payload;
  if (data && data.success === false) {
    throw new Error(data.error || `${action} failed`);
  }
  return data;
}

function findWebbridgeBinary() {
  const candidates = [];
  if (process.env.KIMI_WEBBRIDGE_BIN) candidates.push(process.env.KIMI_WEBBRIDGE_BIN);
  const locator = spawnSync(process.platform === "win32" ? "where" : "which", ["kimi-webbridge"], {
    encoding: "utf8",
  });
  if (locator.status === 0 && locator.stdout.trim()) {
    candidates.push(locator.stdout.trim().split(/\r?\n/)[0]);
  }
  candidates.push(path.join(os.homedir(), ".kimi-webbridge", "bin",
    process.platform === "win32" ? "kimi-webbridge.exe" : "kimi-webbridge"));
  return candidates.find((candidate) => candidate && fs.existsSync(candidate)) || null;
}

async function ensureWebbridge(session) {
  const startedAt = new Date().toISOString();
  try {
    await webbridge("list_tabs", {}, session);
    return {
      tool: "kimi-webbridge",
      attempted: true,
      status: "available",
      command: "list_tabs",
      auto_start_attempted: false,
      error: null,
      timestamp: startedAt,
    };
  } catch (initialError) {
    const binary = findWebbridgeBinary();
    if (!binary) {
      return {
        tool: "kimi-webbridge",
        attempted: true,
        status: "unavailable",
        command: "list_tabs",
        auto_start_attempted: false,
        error: `${initialError.message}; Kimi WebBridge CLI not installed or declared`,
        timestamp: startedAt,
      };
    }

    const start = spawnSync(binary, ["start"], { encoding: "utf8", timeout: 15000 });
    const startError = start.error?.message || (start.status === 0 ? "" : (start.stderr || `exit ${start.status}`).trim());
    for (let attempt = 0; attempt < 10; attempt += 1) {
      await sleep(500);
      try {
        await webbridge("list_tabs", {}, session);
        return {
          tool: "kimi-webbridge",
          attempted: true,
          status: "recovered",
          command: `${binary} start`,
          auto_start_attempted: true,
          error: null,
          initial_error: initialError.message,
          timestamp: startedAt,
        };
      } catch (_) {
        // Keep polling until the local daemon and extension have connected.
      }
    }
    return {
      tool: "kimi-webbridge",
      attempted: true,
      status: "unavailable",
      command: `${binary} start`,
      auto_start_attempted: true,
      error: startError || `${initialError.message}; daemon did not become ready`,
      timestamp: startedAt,
    };
  }
}

async function verifyInBrowser(article, index, session) {
  const candidateUrl = article.url;
  if (!candidateUrl) {
    return { ...article, verification: "failed", verification_error: "missing candidate URL" };
  }

  try {
    await webbridge("navigate", {
      url: candidateUrl,
      newTab: index === 0,
      ...(index === 0 ? { group_title: "公众号原文核验" } : {}),
    }, session);

    // Sogou commonly performs more than one client-side redirect. Poll the
    // live tab instead of treating its signed intermediate URL as evidence.
    let page;
    for (let attempt = 0; attempt < 8; attempt += 1) {
      await sleep(attempt === 0 ? 1800 : 700);
      page = await webbridge("evaluate", { code: `(() => {
        const text = (selector) => document.querySelector(selector)?.textContent?.trim() || "";
        const meta = (name) => document.querySelector('meta[name="' + name + '"]')?.content ||
          document.querySelector('meta[property="' + name + '"]')?.content || "";
        const body = text("#js_content") || text("article");
        const rawDate = text("#publish_time") || text("#js_publish_time") ||
          meta("article:published_time") || meta("og:article:published_time") ||
          (typeof window.ct !== "undefined" ? String(window.ct) : "") ||
          (typeof window.publish_time !== "undefined" ? String(window.publish_time) : "");
        return JSON.stringify({
          url: location.href,
          title: meta("og:title") || text("#activity-name") || document.title,
          account: meta("profile_nickname") || text("#js_name") || text(".profile_nickname"),
          published_at_raw: rawDate,
          body_text: body,
          body_length: body.length
        });
      })()` }, session);
      const value = page && Object.prototype.hasOwnProperty.call(page, "value") ? page.value : page;
      if (typeof value === "string") page = JSON.parse(value);
      else page = value || {};
      if (/^https:\/\/mp\.weixin\.qq\.com\/s(?:[/?]|$)/.test(page.url || "") && page.body_length > 0) break;
    }

    const isWechatArticle = /^https:\/\/mp\.weixin\.qq\.com\/s(?:[/?]|$)/.test(page.url || "");
    const titleMatches = normalizeText(article.title) === normalizeText(page.title);
    const accountMatches = normalizeText(article.source) === normalizeText(page.account);
    const dateMatches = dateKey(article.published_at) === dateKey(page.published_at_raw);
    const bodyReadable = page.body_length > 0;
    const verified = isWechatArticle && titleMatches && accountMatches && dateMatches && bodyReadable;
    const checks = {
      wechat_url: isWechatArticle,
      title: titleMatches,
      account: accountMatches,
      published_at: dateMatches,
      body: bodyReadable,
    };
    const resolvedUrl = isWechatArticle ? canonicalizeWechatUrl(page.url) : null;
    checks.stable_url = Boolean(resolvedUrl);
    const fullyVerified = verified && Boolean(resolvedUrl);
    const allFailedChecks = Object.entries(checks).filter(([, passed]) => !passed).map(([name]) => name);
    return {
      ...article,
      candidate_url: candidateUrl,
      url: fullyVerified ? resolvedUrl : candidateUrl,
      resolved_url: resolvedUrl,
      verified_title: page.title || null,
      verified_account: page.account || null,
      verified_published_at_raw: page.published_at_raw || null,
      body_text: bodyReadable ? page.body_text : null,
      body_length: page.body_length || 0,
      verification_checks: checks,
      verification: fullyVerified ? "verified" : "failed",
      verification_error: fullyVerified ? null : `failed checks: ${allFailedChecks.join(", ")}`,
    };
  } catch (error) {
    return {
      ...article,
      candidate_url: candidateUrl,
      resolved_url: null,
      verification: "failed",
      verification_error: error.message,
    };
  }
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
  } else if (value === "-r" || value === "--resolve-url" || value === "--verify-browser") {
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
const candidates = dated.slice(0, requested);

(async () => {
  const session = `wechat-research-${Date.now()}`;
  const articles = [];
  const toolAttempts = [];
  if (resolveUrl) {
    const webbridgeStatus = await ensureWebbridge(session);
    toolAttempts.push(webbridgeStatus);
    // A WebBridge session has one current tab. Verify sequentially so one
    // candidate cannot navigate away while another candidate is being read.
    for (let index = 0; index < candidates.length; index += 1) {
      articles.push(await verifyInBrowser(candidates[index], index, session));
    }
  } else {
    articles.push(...candidates.map((article) => ({ ...article, verification: "candidate_only" })));
  }
  const verified = articles.filter((article) => article.verification === "verified").length;

  process.stdout.write(`${JSON.stringify({
    ok: true,
    channel: "sogou-weixin",
    verification_channel: resolveUrl ? "kimi-webbridge" : null,
    tool_attempts: toolAttempts,
    query,
    requested,
    returned: articles.length,
    verified,
    date_from: cutoff.toISOString(),
    date_to: now.toISOString(),
    excluded_outside_window_or_invalid_date: excludedOutsideWindowOrInvalidDate,
    excluded_missing_date: undated.length,
    articles,
  }, null, 2)}\n`);
})().catch((error) => {
  console.error(JSON.stringify({ ok: false, error: error.message }));
  process.exit(1);
});
