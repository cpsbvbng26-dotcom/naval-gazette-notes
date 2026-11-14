#!/usr/bin/env node
/* Checked intake (突き合わせの受付).
 *
 * No system can stop a person from lying in general. What a system can do is accept a claim only when it can be checked
 * against a source that the claimant does not write at the moment of claiming, and turn away automatically every claim
 * that fails the check or cannot be checked. Then every accepted claim is a checked claim.
 *
 * This file is the same, byte for byte, in every repository that uses it. What differs is config.json beside it.
 *
 *   node .github/checked-intake/verify.js           in GitHub Actions (.github/workflows/checked-intake.yml)
 *   node .github/checked-intake/verify.js --test    the self-test: every branch, on fixtures that this file makes
 *   node .github/checked-intake/verify.js --check   config.json against this repository: every file it names exists,
 *                                                   and every DOI it maps is named in the README
 *
 * The issue is read from the event file (GITHUB_EVENT_PATH), never from the environment or the shell: a step's
 * environment is printed in the run's log, which would keep the text after the issue is emptied.
 *
 * Kinds of claim (config.json "forms", by the label that the issue form sets):
 *   quote     The words quoted occur in the document at the location given: a file of this repository, a page that it
 *             serves (config "pages"), a file on github.com in this repository (config "blob"), or a DOI or an id that
 *             config.json maps to files of this repository ("dois", "ids"). White space, Unicode compatibility forms,
 *             curly quotation marks and a hyphen at the end of a PDF line are normalised. A page or section given after
 *             the location is not checked: the whole document is searched. A PDF is read with pdftotext.
 *   identity  The ORCID iD has a valid check digit; the public ORCID record of that iD links
 *             https://github.com/<the account that opened the issue>; and, when a DOI is given, the DOI metadata
 *             (DataCite, then Crossref) lists that iD for a creator. Reads pub.orcid.org, api.datacite.org and
 *             api.crossref.org only, and only in a repository whose config.json has a form of this kind.
 *
 * A claim that fails is closed as not planned, with a fixed comment in Japanese and English that names the failed check
 * and how to open a new issue. A claim that passes gets the label "quote verified" or "identity verified"; a person still
 * decides what it means. When the check itself cannot run (pdftotext missing, a service not answering), the issue stays
 * open with the label "not checked".
 *
 * Never closed: an issue with a label in config "neverClose", and an issue whose title or text reads as a request that
 * the law requires the operator to receive or consider (LEGAL below: removal or takedown, rights, personal data,
 * statements about a person, consent and its withdrawal). The check still runs on such an issue and labels it, but the
 * issue stays open with the label "needs a person".
 *
 * It acts only on an issue opened on or after config "from" (a day in Japan time), so that a rule announced ahead takes
 * effect on its day; an earlier issue is left as it is.
 *
 * Nothing that the claimant wrote is written back: comments are fixed texts, and the log carries only fixed words,
 * counts and the issue number. Nothing is stored.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { execFileSync } = require('child_process');

const HERE = __dirname;
const ROOT = path.join(HERE, '..', '..');
const MARK = '<!-- checked-intake -->';
const LABELS = { quote: 'quote verified', identity: 'identity verified', notFound: 'not verified', notChecked: 'not checked', person: 'needs a person' };

/* ------------------------------------------------------------ requests that are never turned away */

/* The words of a request that the law requires the operator to receive or consider. A match never closes the issue.
 * The list is wide on purpose: a word that also occurs in an ordinary report only costs a reading by a person. */
const LEGAL = new RegExp([
  '削除', '取り下げ', '取下げ', '撤回', '開示', '利用停止', '消去', '第三者提供', '提供の停止', '個人情報', '個人データ', '保有個人データ',
  '権利侵害', '侵害', '著作権', '名誉', '信用', 'プライバシー', '肖像', '発信者情報', '送信防止', '同意', '苦情', '辞退',
  '氏名', '名前', '自分について', '私について', 'my name', 'about me', 'my own data',
  'take ?down', 'remov', 'delet', 'eras', 'infring', 'copyright', 'dmca', 'privacy', 'personal (data|information)',
  'data protection', 'gdpr', '\\bappi\\b', 'defam', 'libel', 'slander', 'reputation', 'rectif', 'objection', 'object to',
  'opt.?out', 'consent', 'withdraw', 'complain', 'access request', 'subject access',
].join('|'), 'i');
/* Pure: the words a person wrote, without the fixed lines of the form (its headings and its ticked boxes): the boxes
 * themselves speak of consent and personal data, and would otherwise make every report read as a request. */
const ownWords = (body) => String(body || '').replace(/\r\n/g, '\n').split('\n').filter((l) => !/^### /.test(l) && !/^- \[[ xX]\] /.test(l)).join('\n');
const legalRequest = (text) => LEGAL.test(ownWords(text));

/* ------------------------------------------------------------ the issue */

/* GitHub renders an issue form as "### Label" followed by the answer. Returns { label: answer }. */
function parseForm(body) {
  const out = {};
  for (const part of String(body || '').replace(/\r\n/g, '\n').split(/^### /m).slice(1)) {
    const nl = part.indexOf('\n');
    const label = (nl < 0 ? part : part.slice(0, nl)).trim();
    const value = (nl < 0 ? '' : part.slice(nl + 1)).trim();
    out[label] = value === '_No response_' ? '' : value;
  }
  return out;
}
const field = (form, labels) => { for (const l of labels || []) if (form[l] !== undefined) return form[l]; return ''; };

/* ------------------------------------------------------------ text */

const CJK = '\\u3000-\\u30ff\\u3400-\\u4dbf\\u4e00-\\u9fff\\uf900-\\ufaff\\uff00-\\uffef';
/* Pure: the text as it is compared. NFKC, curly quotes made straight, white space made one space, and no space beside a
 * Japanese or Chinese character (lines break inside words there). With pdf, a hyphen that ends a line joins the word. */
function normalise(s, { pdf = false } = {}) {
  let t = String(s || '').normalize('NFKC').replace(/­/g, '');
  if (pdf) t = t.replace(/([A-Za-z])-\s*\n\s*([a-z])/g, '$1$2');
  t = t.replace(/[‘’‚′]/g, "'").replace(/[“”„″]/g, '"').replace(/\s+/g, ' ');
  t = t.replace(new RegExp('([' + CJK + ']) (?=[' + CJK + '])', 'g'), '$1').replace(new RegExp('([' + CJK + ']) ', 'g'), '$1').replace(new RegExp(' ([' + CJK + '])', 'g'), '$1');
  return t.trim();
}

/* Pure: the quoted words as given, without one pair of surrounding quotation marks or a leading "> ". */
function quoteOf(s) {
  let t = String(s || '').replace(/\r\n/g, '\n').split('\n').map((l) => l.replace(/^>\s?/, '')).join('\n').trim();
  const pairs = [['「', '」'], ['『', '』'], ['“', '”'], ['"', '"'], ["'", "'"], ['‘', '’']];
  for (const [a, b] of pairs) if (t.length > 1 && t.startsWith(a) && t.endsWith(b)) { t = t.slice(a.length, -b.length); break; }
  return t;
}
const QUOTE_MIN = 6;
const QUOTE_MAX = 2000;
const visible = (t) => t.replace(/\s/g, '').length;

/* Pure: the plain text of a page: scripts, styles and tags dropped, entities decoded. */
function htmlText(s) {
  const ent = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ' };
  return String(s || '').replace(/<script[\s\S]*?<\/script>/gi, ' ').replace(/<style[\s\S]*?<\/style>/gi, ' ').replace(/<[^>]+>/g, ' ')
    .replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, e) => (e[0] === '#' ? String.fromCodePoint(e[1] === 'x' || e[1] === 'X' ? parseInt(e.slice(2), 16) : Number(e.slice(1))) : ent[e.toLowerCase()] !== undefined ? ent[e.toLowerCase()] : m));
}
/* Pure: Markdown as it reads: emphasis, code marks and the targets of links dropped. */
const markdownText = (s) => String(s || '').replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/[*_`]+/g, '').replace(/^#+\s*/gm, '').replace(/^>\s?/gm, '').replace(/\\([\\`*_{}[\]()#+\-.!|])/g, '$1');

const TEXT_EXT = new Set(['.md', '.txt', '.html', '.htm', '.json', '.toml', '.yml', '.yaml', '.csv', '.tsv', '.bib', '.tex', '.py', '.js', '.cff', '.xml', '.svg', '.css', '.ris']);

/* The readings of a file, each normalised: a file can match as written or as it reads. Throws { notChecked } when the
 * file is a PDF and pdftotext cannot run. */
function readings(file, pdftotext = defaultPdftotext) {
  const ext = path.extname(file).toLowerCase();
  if (ext === '.pdf') return [normalise(pdftotext(file), { pdf: true })];
  if (!TEXT_EXT.has(ext)) return null;
  const raw = fs.readFileSync(file, 'utf8');
  /* A page is read as it shows: its scripts, styles and tags are not words of the page. */
  if (ext === '.html' || ext === '.htm') return [normalise(htmlText(raw))];
  const out = [normalise(raw)];
  if (ext === '.md') out.push(normalise(markdownText(raw)));
  if (ext === '.svg' || ext === '.xml') out.push(normalise(htmlText(raw)));
  return out;
}
function defaultPdftotext(file) {
  try {
    return execFileSync('pdftotext', ['-enc', 'UTF-8', file, '-'], { encoding: 'utf8', timeout: 60000, stdio: ['ignore', 'pipe', 'ignore'], maxBuffer: 64 * 1024 * 1024 });
  } catch (e) {
    const err = new Error('pdftotext could not run');
    err.notChecked = true;
    throw err;
  }
}

/* ------------------------------------------------------------ the location */

const DOI = /(?:^|[\s(（:])(?:https?:\/\/(?:dx\.)?doi\.org\/|doi:\s*)?(10\.\d{4,9}\/[^\s,、，;；)）]+)/i;
/* Pure: the relative path inside the root that a path names, or null when it leaves the root or names .git. */
function inside(root, rel) {
  const clean = String(rel || '').replace(/^\.?\/+/, '');
  if (!clean || clean.split(/[\\/]/).some((s) => s === '..' || s === '.git')) return null;
  const abs = path.resolve(root, clean);
  return abs.startsWith(path.resolve(root) + path.sep) ? path.relative(root, abs) : null;
}
/* Pure (reads only whether files exist): the files of this repository that a location names, or null. */
function resolveLocation(where, conf, root = ROOT) {
  const line = String(where || '').split('\n').map((l) => l.trim()).find(Boolean) || '';
  const text = line.replace(/^`+|`+$/g, '').trim();
  const isFile = (rel) => { const r = inside(root, rel); return r && fs.existsSync(path.join(root, r)) && fs.statSync(path.join(root, r)).isFile() ? r : null; };
  for (const [pattern, template] of conf.ids || []) {
    const m = new RegExp(pattern).exec(text.split(/[\s,、，]/)[0]);
    if (m) { const f = isFile(template.replace(/\{(\d)\}/g, (x, i) => m[Number(i)] || '')); if (f) return [f]; }
  }
  const url = (/https?:\/\/\S+/.exec(text) || [])[0];
  const d = DOI.exec(text);
  if (d && !(url && !/doi\.org/i.test(url))) {
    const key = d[1].replace(/[.。]+$/, '').toLowerCase();
    const hit = Object.entries(conf.dois || {}).find(([k]) => k.toLowerCase() === key);
    if (!hit) return null;
    const files = hit[1].map(isFile);
    return files.every(Boolean) ? files : null;
  }
  if (url) {
    let u;
    try { u = new URL(url.replace(/[)）。、,]+$/, '')); } catch { return null; }
    const pathname = decodeURIComponent(u.pathname);
    if (conf.blob) {
      const b = new URL(conf.blob);
      const base = b.pathname.replace(/\/$/, '');
      if (u.hostname === b.hostname && (pathname === base || pathname.startsWith(base + '/'))) {
        const m = /^\/(?:blob|raw)\/[^/]+\/(.+)$/.exec(pathname.slice(base.length));
        const f = m && isFile(m[1]);
        return f ? [f] : null;
      }
      const raw = /^\/([^/]+)\/([^/]+)\/[^/]+\/(.+)$/.exec(pathname);
      if (u.hostname === 'raw.githubusercontent.com' && raw && ('/' + raw[1] + '/' + raw[2]).toLowerCase() === base.toLowerCase()) {
        const f = isFile(raw[3]);
        return f ? [f] : null;
      }
    }
    for (const p of conf.pages || []) {
      const b = new URL(p.url);
      if (u.hostname !== b.hostname || !pathname.startsWith(b.pathname)) continue;
      const rest = pathname.slice(b.pathname.length);
      const dir = p.dir || '';
      const tries = !rest || rest.endsWith('/') ? [rest + 'index.html'] : path.extname(rest) ? [rest] : [rest + '.html', rest + '/index.html'];
      for (const t of tries) { const f = isFile(path.posix.join(dir, t)); if (f) return [f]; }
      return null;
    }
    return null;
  }
  const token = text.split(/[\s,、，（(]/)[0].replace(/[:：]$/, '');
  const f = token && isFile(token);
  return f ? [f] : null;
}

/* ------------------------------------------------------------ the checks (pure but for reading files) */

/* The result of a quotation: { ok, reason, files }. reason is one of: found, location, short, long, absent, unreadable. */
function checkQuote(form, spec, conf, root = ROOT, pdftotext = defaultPdftotext) {
  const files = resolveLocation(field(form, spec.where), conf, root);
  if (!files) return { ok: false, reason: 'location' };
  const q = quoteOf(field(form, spec.quote));
  if (visible(q) < QUOTE_MIN) return { ok: false, reason: 'short' };
  if (q.length > QUOTE_MAX) return { ok: false, reason: 'long' };
  const variants = [...new Set([normalise(q), normalise(markdownText(q))])].filter(Boolean);
  for (const f of files) {
    const rs = readings(path.join(root, f), pdftotext);
    if (rs === null) return { ok: false, reason: 'unreadable' };
    if (rs.some((r) => variants.some((v) => r.includes(v)))) return { ok: true, reason: 'found', files };
  }
  return { ok: false, reason: 'absent', files };
}

/* Pure: whether an ORCID iD is well formed and its check digit right (ISO 7064 11,2). */
function orcidOk(id) {
  if (!/^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$/.test(String(id || ''))) return false;
  const d = id.replace(/-/g, '');
  let t = 0;
  for (const c of d.slice(0, 15)) t = (t + Number(c)) * 2;
  const r = (12 - (t % 11)) % 11;
  return (r === 10 ? 'X' : String(r)) === d[15];
}
const orcidIn = (s) => (String(s || '').match(/\d{4}-\d{4}-\d{4}-\d{3}[\dX]/) || [''])[0];
/* Pure: whether a list of websites links exactly https://github.com/<login>. */
function linksGithub(urls, login) {
  return (urls || []).some((x) => {
    let u;
    try { u = new URL(x); } catch { return false; }
    const seg = u.pathname.split('/').filter(Boolean);
    return /^https?:$/.test(u.protocol) && /^(www\.)?github\.com$/i.test(u.hostname) && seg.length === 1 && seg[0].toLowerCase() === String(login || '').toLowerCase();
  });
}
/* Pure: the websites of an ORCID researcher-urls answer. */
const orcidUrls = (json) => (((json || {})['researcher-url']) || []).map((u) => (u.url && u.url.value) || '');
/* Pure: the ORCID iDs of the creators in DataCite or Crossref metadata. */
function creatorIds(raw) {
  if (raw && raw.data && raw.data.attributes) {
    return (raw.data.attributes.creators || []).flatMap((c) => (c.nameIdentifiers || []).filter((n) => /orcid/i.test(n.nameIdentifierScheme || '')).map((n) => orcidIn(n.nameIdentifier)));
  }
  if (raw && raw.message) return (raw.message.author || []).map((a) => orcidIn(a.ORCID));
  return [];
}
/* The result of an identity claim: { ok, reason }. reason: verified, orcid, unread, link, doi, creator. `look` fetches. */
async function checkIdentity(form, spec, login, look) {
  const id = orcidIn(field(form, spec.orcid));
  if (!id || !orcidOk(id)) return { ok: false, reason: 'orcid' };
  const urls = await look('orcid', id);
  if (urls === undefined) return { ok: null, reason: 'unread' };
  if (!urls || !linksGithub(orcidUrls(urls), login)) return { ok: false, reason: 'link' };
  const doi = (DOI.exec(' ' + field(form, spec.doi)) || [])[1];
  if (!doi) return { ok: true, reason: 'verified' };
  const meta = await look('doi', doi.replace(/[.。]+$/, ''));
  if (meta === undefined) return { ok: null, reason: 'unread' };
  if (!meta) return { ok: false, reason: 'doi' };
  return creatorIds(meta).includes(id) ? { ok: true, reason: 'verified' } : { ok: false, reason: 'creator' };
}

/* ------------------------------------------------------------ the comments (fixed texts) */

const HEAD = '**突き合わせの受付 / Checked intake**';
const AGAIN = '直した内容で、新しい issue を開けます。この issue は、閉じたまま残ります。\nA new issue can be opened with this corrected. This issue stays closed.';
const TEXTS = {
  found: '示した所に、引いた語がそのとおりにありました。誤りかどうかは、人が読んで決めます。\nThe quoted words occur at the location given, as quoted. Whether this is an error is decided by a person who reads it.',
  location: '「どこか」の欄の所を、このリポジトリのファイル、配っている頁、このリポジトリが写しを持つ DOI のどれとしても見つけられませんでした。ファイルの名（例 `README.md`）、頁の URL、DOI のどれか一つを、欄の初めに書きます。\nThe location could not be found as a file of this repository, a page that it serves, or a DOI of which it holds a copy. The location field begins with one of these: a file name (such as `README.md`), the URL of a page, or a DOI.',
  short: '引いた語が短すぎて、突き合わせになりません。空白を除いて ' + QUOTE_MIN + ' 文字以上を、書いてあるとおりに写します。\nThe quotation is too short to be checked. At least ' + QUOTE_MIN + ' characters, not counting spaces, are copied as printed.',
  long: '引いた語が長すぎます。' + QUOTE_MAX + ' 文字までにします。\nThe quotation is too long. It is at most ' + QUOTE_MAX + ' characters.',
  absent: '示した所に、引いた語が見つかりませんでした。空白の違いは見ていません。一字ずつ、書いてあるとおりに写します。\nThe quoted words were not found at the location given. Differences of white space are ignored; every character is copied as printed.',
  unreadable: '示した所は、文字として読めるファイルではありません。読める所（文書、頁、PDF）を示します。\nThe location is not a file that can be read as text. A document, a page or a PDF is named instead.',
  verified: 'ORCID の公開の記録が、この issue を開いた GitHub のアカウントにつながり、DOI を書いたときは、その DOI の登録情報がこの iD を作成者に挙げていました。\nThe public ORCID record links the GitHub account that opened this issue, and, where a DOI is given, its metadata lists this iD for a creator.',
  orcid: 'ORCID iD の形か検査の数字が正しくありません。\nThe ORCID iD is not well formed, or its check digit is wrong.',
  link: 'その ORCID iD の公開の記録が、この issue を開いた GitHub のアカウントにつながっていません。ORCID の記録の「Websites & social links」に `https://github.com/<アカウント名>` を足せば、つながります。\nThe public ORCID record of that iD does not link the GitHub account that opened this issue. Adding `https://github.com/<username>` under "Websites & social links" in the ORCID record links it.',
  doi: 'その DOI の登録情報を、DataCite からも Crossref からも読めませんでした。\nThe metadata of that DOI could not be read from DataCite or Crossref.',
  creator: 'その DOI の登録情報は、この ORCID iD を作成者に挙げていません。自分の作品の DOI だけを書きます。\nThe metadata of that DOI does not list this ORCID iD for a creator. Only a DOI of one\'s own work is given.',
  unread: '確かめる先が答えず、いまは確かめられませんでした。issue は開いたままにし、人が読みます。\nThe service that the check reads did not answer, so it could not be checked now. The issue stays open for a person.',
  notChecked: 'PDF を読む道具が動かず、いまは確かめられませんでした。issue は開いたままにし、人が読みます。\nThe tool that reads the PDF did not run, so it could not be checked now. The issue stays open for a person.',
  person: 'この issue は、法令が受け取ることを求める求め（削除、権利、個人の情報、人についての記述、同意とその撤回）を含むかもしれません。突き合わせの受付は、この issue を閉じません。人が読んで扱います。\nThis issue may contain a request that the law requires the operator to receive (removal, rights, personal data, statements about a person, consent and its withdrawal). The checked intake does not close it. A person reads and handles it.',
};
/* Pure: the comment for a result. Nothing of the issue is written in it. */
function commentFor(result, { legal = false } = {}) {
  const lines = [MARK, HEAD, '', TEXTS[result.reason]];
  if (result.ok === false && !legal) lines.push('', AGAIN);
  if (legal) lines.push('', TEXTS.person);
  return lines.join('\n') + '\n';
}
/* Pure: what to do with the issue: { close, add: [labels], remove: [labels] }. A legal request is never closed. */
function actionFor(kind, result, { legal = false } = {}) {
  const pass = kind === 'identity' ? LABELS.identity : LABELS.quote;
  const all = [LABELS.quote, LABELS.identity, LABELS.notFound, LABELS.notChecked];
  const add = result.ok === true ? [pass] : result.ok === false ? [LABELS.notFound] : [LABELS.notChecked];
  if (legal) add.push(LABELS.person);
  return { close: result.ok === false && !legal, add, remove: all.filter((l) => !add.includes(l)) };
}

/* Pure: whether a form's claim is one that the intake checks. A form spec may limit it to some answers of one field
 * ("when": { "field": [labels], "in": [answers] }); any other answer, such as "Something else", is left to a person. */
function applies(spec, form) {
  if (!spec.when) return true;
  return (spec.when.in || []).includes(String(field(form, spec.when.field) || '').trim());
}

/* ------------------------------------------------------------ the run */

function loadConf(dir = HERE) { return JSON.parse(fs.readFileSync(path.join(dir, 'config.json'), 'utf8')); }

/* Pure: the day of a time in Japan time (YYYY-MM-DD), or null. */
function jstDay(t) {
  const ms = Date.parse(t);
  return Number.isNaN(ms) ? null : new Date(ms + 9 * 3600 * 1000).toISOString().slice(0, 10);
}
/* Pure: the form spec that an issue belongs to, or null (not an issue of the checked intake, one never closed, or one
 * opened before config "from"). */
function specFor(issue, conf) {
  if (conf.from && !(jstDay(issue && issue.created_at) >= conf.from)) return null;
  const names = ((issue && issue.labels) || []).map((l) => (typeof l === 'string' ? l : l.name));
  if (names.some((n) => (conf.neverClose || []).includes(n))) return null;
  return (conf.forms || []).find((f) => names.includes(f.label)) || null;
}

async function request(url, opts = {}) {
  return fetch(url, Object.assign({ signal: AbortSignal.timeout(60000) }, opts, { headers: Object.assign({ 'User-Agent': 'checked-intake (GitHub Actions)' }, opts.headers || {}) }));
}
async function lookUp(kind, id) {
  try {
    if (kind === 'orcid') {
      const r = await request('https://pub.orcid.org/v3.0/' + id + '/researcher-urls', { headers: { Accept: 'application/json' } });
      return r.status === 404 ? null : r.ok ? r.json() : undefined;
    }
    for (const base of ['https://api.datacite.org/dois/', 'https://api.crossref.org/works/']) {
      const r = await request(base + encodeURIComponent(id), { headers: { Accept: 'application/json' } });
      if (r.ok) return r.json();
      if (r.status !== 404) return undefined;
    }
    return null;
  } catch { return undefined; }
}
async function github(method, url, body) {
  const r = await request('https://api.github.com/repos/' + process.env.GITHUB_REPOSITORY + url, {
    method, headers: { Authorization: 'Bearer ' + process.env.GITHUB_TOKEN, Accept: 'application/vnd.github+json', 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok && r.status !== 404) throw new Error(method + ' ' + url.split('?')[0] + ': HTTP ' + r.status);
  return r.status === 204 || r.status === 404 ? null : r.json();
}

/* One run on one event. Everything outside is passed in: the event, the configuration, the root of the files, the GitHub
 * call (gh), the look-up for identity (look) and the log (say), so that the self-test runs it on events it makes. */
async function run({ event, conf, root = ROOT, gh, look = lookUp, say = console.log, pdftotext = defaultPdftotext }) {
  const issue = event.issue || {};
  const n = issue.number;
  if (!Number.isInteger(n) || issue.pull_request || !['opened', 'edited', 'reopened'].includes(event.action) || issue.state === 'closed') return say('nothing to check');
  const spec = specFor(issue, conf);
  if (!spec) return say('issue ' + n + ': not a form of the checked intake');
  const form = parseForm(issue.body);
  if (!applies(spec, form)) return say('issue ' + n + ': a kind that the checked intake leaves to a person');
  const legal = legalRequest(issue.title) || legalRequest(issue.body);
  let result;
  try {
    result = spec.kind === 'identity'
      ? await checkIdentity(form, spec, (issue.user && issue.user.login) || '', look)
      : checkQuote(form, spec, conf, root, pdftotext);
  } catch (e) {
    if (!e.notChecked) throw e;
    result = { ok: null, reason: 'notChecked' };
  }
  const act = actionFor(spec.kind, result, { legal });
  const body = commentFor(result, { legal });
  const comments = (await gh('GET', '/issues/' + n + '/comments?per_page=100')) || [];
  const mine = comments.find((c) => c.user && c.user.type === 'Bot' && String(c.body || '').startsWith(MARK));
  if (mine) await gh('PATCH', '/issues/comments/' + mine.id, { body });
  else await gh('POST', '/issues/' + n + '/comments', { body });
  for (const l of act.remove) await gh('DELETE', '/issues/' + n + '/labels/' + encodeURIComponent(l));
  await gh('POST', '/issues/' + n + '/labels', { labels: act.add });
  if (act.close) await gh('PATCH', '/issues/' + n, { state: 'closed', state_reason: 'not_planned' });
  say('issue ' + n + ': ' + (spec.kind === 'identity' ? 'identity' : 'quote') + ' ' + (result.ok === true ? 'verified' : result.ok === false ? 'not verified' : 'not checked') + (act.close ? ', closed' : '') + (legal ? ', left for a person' : ''));
}

async function main() {
  const event = JSON.parse(fs.readFileSync(process.env.GITHUB_EVENT_PATH, 'utf8'));
  await run({ event, conf: loadConf(), gh: github });
}

/* ------------------------------------------------------------ --check: config.json against the repository */

function configProblems(conf, root = ROOT) {
  const bad = [];
  if (!Array.isArray(conf.forms) || !conf.forms.length) bad.push('no forms');
  if (!/^\d{4}-\d{2}-\d{2}$/.test(conf.from || '')) bad.push('from: not a day');
  for (const f of conf.forms || []) {
    if (!['quote', 'identity'].includes(f.kind)) bad.push('form ' + f.label + ': unknown kind');
    if ((conf.neverClose || []).includes(f.label)) bad.push('form ' + f.label + ': a label that is never closed');
    if (LEGAL.test(f.label)) bad.push('form ' + f.label + ': the label of a request');
    if (f.when && (!Array.isArray(f.when.field) || !Array.isArray(f.when.in) || !f.when.in.length)) bad.push('form ' + f.label + ': a "when" without a field and answers');
    const need = f.kind === 'identity' ? ['orcid', 'doi'] : ['where', 'quote'];
    for (const k of need) if (!Array.isArray(f[k]) || !f[k].length) bad.push('form ' + f.label + ': no labels for ' + k);
  }
  const readme = ['README.md', 'README.en.md'].map((r) => (fs.existsSync(path.join(root, r)) ? fs.readFileSync(path.join(root, r), 'utf8') : '')).join('\n');
  for (const [doi, files] of Object.entries(conf.dois || {})) {
    if (!readme.includes(doi)) bad.push(doi + ': not named in the README');
    for (const f of files) if (!inside(root, f) || !fs.existsSync(path.join(root, f))) bad.push(doi + ': ' + f + ' missing');
  }
  for (const p of conf.pages || []) if (!/^https:\/\/[^/]+\/(.*\/)?$/.test(p.url)) bad.push('page ' + p.url + ': not an https address ending in /');
  if (conf.blob && !/^https:\/\/github\.com\/[^/]+\/[^/]+$/.test(conf.blob)) bad.push('blob: not a repository on github.com');
  return bad;
}

/* ------------------------------------------------------------ --test: every branch, on fixtures made here */

/* A PDF with one page and the given line of text in Helvetica, written by this code. */
function fixturePdf(line) {
  const esc = line.replace(/[\\()]/g, (c) => '\\' + c);
  const stream = 'BT /F1 12 Tf 72 720 Td (' + esc + ') Tj ET';
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    '<< /Length ' + stream.length + ' >>\nstream\n' + stream + '\nendstream', '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  let out = '%PDF-1.4\n';
  const at = [];
  objs.forEach((o, i) => { at.push(out.length); out += (i + 1) + ' 0 obj\n' + o + '\nendobj\n'; });
  const x = out.length;
  out += 'xref\n0 ' + (objs.length + 1) + '\n0000000000 65535 f \n' + at.map((a) => String(a).padStart(10, '0') + ' 00000 n \n').join('');
  return out + 'trailer\n<< /Size ' + (objs.length + 1) + ' /Root 1 0 R >>\nstartxref\n' + x + '\n%%EOF\n';
}

async function selfTest() {
  const os = require('os');
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'checked-intake-'));
  const put = (rel, text) => { fs.mkdirSync(path.dirname(path.join(root, rel)), { recursive: true }); fs.writeFileSync(path.join(root, rel), text); };
  put('README.md', '# Fixture\n\nThe frozen paper is 10.5555/fixture.1000001.\n');
  put('ERRATA.md', '# 正誤表\n\n第二節の式は、**収束する**と書いてある。\nThe sum converges to “one half” for every\nstarting point.\n');
  put('docs/page.html', '<html><body><p>The site says <b>forty&nbsp;two</b> &amp; more.</p><script>var hidden = "never seen";</script></body></html>');
  put('docs/index.html', '<p>Index page of the docs.</p>');
  put('site/abs/2026.0001.html', '<h1>A record title for the fixture</h1>');
  put('image.png', 'not text');
  let havePdf = true;
  try { execFileSync('pdftotext', ['-v'], { stdio: 'ignore' }); } catch { havePdf = false; }
  put('pdf/paper.pdf', fixturePdf('The operator is a contraction on the simplex.'));
  const conf = {
    forms: [{ label: 'erratum', kind: 'quote', where: ['Where'], quote: ['What it says'] }, { label: 'bug', kind: 'identity', orcid: ['Your ORCID iD'], doi: ['Your DOI (optional)'] }],
    pages: [{ url: 'https://example.github.io/fixture/', dir: 'docs' }, { url: 'https://records.example/', dir: 'site' }],
    blob: 'https://github.com/example/fixture',
    dois: { '10.5555/fixture.1000001': ['pdf/paper.pdf'] },
    ids: [['^(\\d{4}\\.\\d{4})$', 'site/abs/{1}.html']],
    neverClose: ['removal'],
    from: '2026-12-01',
  };
  const results = [];
  const t = (name, ok) => results.push([name, !!ok]);
  const form = (where, quote) => parseForm('### Where\n\n' + where + '\n\n### What it says\n\n' + quote + '\n\n### Found by\n\nReader\n');
  const spec = conf.forms[0];
  const q = (where, quote, pt) => checkQuote(form(where, quote), spec, conf, root, pt);
  /* quote: every branch */
  t('a file and its words, across a line break and emphasis', q('ERRATA.md', '第二節の式は、収束すると書いてある。').ok);
  t('curly quotes and a line break in English', q('ERRATA.md, line 4', 'The sum converges to "one half" for every starting point.').ok);
  t('a quotation in 「」 and a leading > are taken off', q('ERRATA.md', '> 「第二節の式は、収束する」').ok);
  t('a page served from a directory, entities decoded, scripts not read', q('https://example.github.io/fixture/page', 'says forty two & more').ok && q('https://example.github.io/fixture/page.html', 'var hidden').reason === 'absent');
  t('the index of a directory', q('https://example.github.io/fixture/', 'Index page of the docs').ok);
  t('a file on github.com, and its raw copy', q('https://github.com/example/fixture/blob/main/ERRATA.md#L3', '収束すると書いてある').ok && q('https://raw.githubusercontent.com/example/fixture/main/ERRATA.md', '収束すると書いてある').ok);
  t('an id of a record', q('2026.0001', 'A record title for the fixture').ok);
  t('a DOI with a page after it, read from the PDF', !havePdf || (q('https://doi.org/10.5555/fixture.1000001, p. 1', 'is a contraction on the simplex').ok && q('10.5555/fixture.1000001', 'is an expansion').reason === 'absent'));
  t('pdftotext missing: not checked, never closed', (() => { try { q('pdf/paper.pdf', 'is a contraction', () => { const e = new Error('x'); e.notChecked = true; throw e; }); return false; } catch (e) { return !!e.notChecked; } })());
  t('words that are not there', q('ERRATA.md', '第二節の式は、発散すると書いてある。').reason === 'absent');
  t('a location that is not a file', q('nowhere.md', '第二節の式は').reason === 'location' && q('docs', 'Index page').reason === 'location' && q('', 'something long enough').reason === 'location');
  t('a path that leaves the repository or names .git', q('../outside.md', 'something long enough').reason === 'location' && q('.git/config', 'something long enough').reason === 'location');
  t('a DOI that this repository does not hold', q('10.5555/fixture.9999999', 'something long enough').reason === 'location');
  t('a page of another site', q('https://elsewhere.example/page.html', 'something long enough').reason === 'location');
  t('a file of another repository on github.com', q('https://github.com/example/other/blob/main/ERRATA.md', '収束すると書いてある').reason === 'location');
  t('a quotation too short, and too long', q('ERRATA.md', '収束') .reason === 'short' && q('ERRATA.md', 'x'.repeat(QUOTE_MAX + 1)).reason === 'long');
  t('a file that is not text', q('image.png', 'not text at all').reason === 'unreadable');
  /* identity: every branch, with answers made here */
  const ID = '0000-0002-1825-0097';
  const answers = { orcid: { [ID]: { 'researcher-url': [{ url: { value: 'https://github.com/alice' } }] } }, doi: { '10.5555/own': { data: { attributes: { creators: [{ nameIdentifiers: [{ nameIdentifierScheme: 'ORCID', nameIdentifier: 'https://orcid.org/' + ID }] }] } } }, '10.5555/crossref': { message: { author: [{ ORCID: 'http://orcid.org/' + ID }] } }, '10.5555/other': { data: { attributes: { creators: [{ name: 'Someone' }] } } } } };
  const look = async (k, id) => (k === 'orcid' ? answers.orcid[id] || null : answers.doi[id] || null);
  const down = async () => undefined;
  const idf = (orcid, doi) => parseForm('### Your ORCID iD\n\n' + orcid + '\n\n### Your DOI (optional)\n\n' + (doi || '_No response_') + '\n');
  const I = async (o, d, login, lk = look) => (await checkIdentity(idf(o, d), conf.forms[1], login, lk)).reason;
  t('identity: a linked account, without a DOI', (await I(ID, '', 'alice')) === 'verified');
  t('identity: a DOI that lists the iD, at DataCite and at Crossref', (await I(ID, '10.5555/own', 'Alice')) === 'verified' && (await I(ID, 'https://doi.org/10.5555/crossref', 'alice')) === 'verified');
  t('identity: a wrong check digit', (await I('0000-0002-1825-0098', '', 'alice')) === 'orcid' && (await I('not an id', '', 'alice')) === 'orcid');
  t('identity: another account', (await I(ID, '', 'mallory')) === 'link' && (await I('0000-0001-5109-3700', '', 'alice')) === 'link');
  t('identity: a DOI of someone else, and one that cannot be read', (await I(ID, '10.5555/other', 'alice')) === 'creator' && (await I(ID, '10.5555/none', 'alice')) === 'doi');
  t('identity: a service that does not answer is not checked, never closed', (await I(ID, '', 'alice', down)) === 'unread' && actionFor('identity', { ok: null, reason: 'unread' }).close === false);
  t('identity: a link that is not exactly the account', !linksGithub(['https://github.com/alice/repo', 'https://gist.github.com/alice', 'https://github.com.example/alice'], 'alice') && linksGithub(['https://www.github.com/alice/'], 'alice'));
  /* what is done, and what is written */
  t('a pass labels and never closes; a fail closes; not checked stays open', actionFor('quote', { ok: true }).close === false && actionFor('quote', { ok: true }).add[0] === LABELS.quote
    && actionFor('quote', { ok: false, reason: 'absent' }).close === true && actionFor('quote', { ok: null, reason: 'notChecked' }).close === false);
  t('a legal request is never closed, and is left for a person', actionFor('quote', { ok: false, reason: 'absent' }, { legal: true }).close === false && actionFor('quote', { ok: false, reason: 'absent' }, { legal: true }).add.includes(LABELS.person));
  t('the ticked boxes and headings of a form are not read as a request', !legalRequest('### Use of a language model\n\n- [X] I consent to the operator giving the title and text of this issue to Claude.\n- [X] This issue contains no personal data.\n') && legalRequest('### What it says\n\nI consent to nothing; remove it.\n'));
  t('the words of a legal request are seen in Japanese and English', ['この記載の削除を求めます', '個人情報の開示を求めます', '私の氏名の綴りが違います', 'My name is misspelt on the record', '名誉を傷つける', '同意を撤回します', 'Please take down this', 'remove my name', 'my personal data', 'copyright infringement', 'I withdraw my consent', 'GDPR erasure'].every(legalRequest)
    && !legalRequest('第二節の式の符号が逆です。The sign in section 2 is wrong.'));
  const on = '2026-11-30T15:00:00Z', before = '2026-11-30T14:59:59Z';
  t('an issue with a label never closed is not taken, and one without a form label is not taken', specFor({ labels: [{ name: 'erratum' }, { name: 'removal' }], created_at: on }, conf) === null && specFor({ labels: [{ name: 'question' }], created_at: on }, conf) === null && specFor({ labels: ['erratum'], created_at: on }, conf) === spec);
  t('an issue opened before the day of "from" (Japan time) is not taken', specFor({ labels: ['erratum'], created_at: before }, conf) === null && specFor({ labels: ['erratum'] }, conf) === null);
  const limited = Object.assign({}, spec, { when: { field: ['Kind'], in: ['The title is wrong'] } });
  t('a form limited to some kinds takes only those, and leaves any other kind to a person', applies(limited, parseForm('### Kind\n\nThe title is wrong\n')) && !applies(limited, parseForm('### Kind\n\nSomething else\n')) && !applies(limited, parseForm('')) && applies(spec, parseForm('')));
  const planted = 'PLANTED-WORDS-OF-THE-CLAIMANT';
  const r1 = q('ERRATA.md', planted + ' long enough');
  t('a comment never repeats what was written', Object.keys(TEXTS).every((k) => !commentFor({ ok: false, reason: k }).includes(planted)) && !commentFor(r1).includes(planted) && commentFor(r1).startsWith(MARK));
  t('a comment of a fail says how to open a new issue; one of a legal request does not say it is closed', commentFor({ ok: false, reason: 'absent' }).includes(AGAIN) && !commentFor({ ok: false, reason: 'absent' }, { legal: true }).includes(AGAIN));
  t('the configuration of the fixture has no problem, and a broken one has', configProblems(conf, root).length === 0
    && configProblems(Object.assign({}, conf, { forms: [{ label: 'removal', kind: 'quote', where: ['W'], quote: ['Q'] }] }), root).length > 0
    && configProblems(Object.assign({}, conf, { dois: { '10.5555/fixture.2': ['pdf/paper.pdf'] } }), root).length > 0
    && configProblems(Object.assign({}, conf, { dois: { '10.5555/fixture.1000001': ['pdf/none.pdf'] } }), root).length > 0);
  /* Whole runs on events made here: what is called on GitHub, and what is logged. */
  const ev = (o) => ({ action: o.action || 'opened', issue: Object.assign({ number: 7, state: 'open', created_at: on, title: 'PLANTED-TITLE', user: { login: 'alice' }, labels: [{ name: 'erratum' }] }, o.issue || {}) });
  const runOn = async (e, lk = look) => {
    const calls = [], logs = [];
    const gh = async (method, url, body) => { calls.push({ method, url, body }); return method === 'GET' ? [] : {}; };
    await run({ event: e, conf, root, gh, look: lk, say: (x) => logs.push(String(x)) });
    const text = JSON.stringify(calls) + logs.join('\n');
    return { calls, logs, closed: calls.some((c) => c.method === 'PATCH' && c.url === '/issues/7' && c.body.state === 'closed'), labels: (calls.find((c) => c.method === 'POST' && /\/labels$/.test(c.url)) || { body: { labels: [] } }).body.labels, leak: /PLANTED/.test(text) };
  };
  const bodyOf = (where, quote, extra = '') => '### Where\n\n' + where + '\n\n### What it says\n\n' + quote + '\n\n### What it should say\n\nPLANTED-BODY ' + extra + '\n';
  const e1 = await runOn(ev({ issue: { body: bodyOf('ERRATA.md', 'PLANTED words that are not there') } }));
  t('an event whose words are not there: a fixed comment, the label "not verified", closed, and nothing of the issue in the calls or the log', e1.closed && e1.labels.includes(LABELS.notFound) && !e1.leak && e1.calls.some((c) => c.method === 'POST' && /\/comments$/.test(c.url)));
  const e2 = await runOn(ev({ issue: { body: bodyOf('ERRATA.md', '第二節の式は、収束すると書いてある。') } }));
  t('an event whose words are there: the label "quote verified", not closed', !e2.closed && e2.labels.includes(LABELS.quote) && !e2.leak);
  const e3 = await runOn(ev({ issue: { body: bodyOf('ERRATA.md', 'PLANTED words that are not there', 'Please remove my personal data from this page.') } }));
  t('an event that reads as a request is not closed even when its words are not there, and is left for a person', !e3.closed && e3.labels.includes(LABELS.person) && !e3.leak);
  const quiet = await Promise.all([
    runOn(ev({ issue: { created_at: before, body: bodyOf('ERRATA.md', 'PLANTED words that are not there') } })),
    runOn(ev({ issue: { labels: [{ name: 'erratum' }, { name: 'removal' }], body: bodyOf('ERRATA.md', 'PLANTED words that are not there') } })),
    runOn(ev({ issue: { labels: [{ name: 'question' }], body: bodyOf('ERRATA.md', 'PLANTED words that are not there') } })),
    runOn(ev({ action: 'closed', issue: { body: bodyOf('ERRATA.md', 'PLANTED words that are not there') } })),
    runOn(ev({ issue: { state: 'closed', body: bodyOf('ERRATA.md', 'PLANTED words that are not there') } })),
    runOn(ev({ issue: { pull_request: {}, body: bodyOf('ERRATA.md', 'PLANTED words that are not there') } })),
  ]);
  t('no call on GitHub for an event before the day, with a label never closed, without a form label, of another action, on a closed issue, or on a pull request', quiet.every((r) => r.calls.length === 0 && !r.leak));
  const e4 = await runOn(ev({ issue: { labels: [{ name: 'bug' }], user: { login: 'mallory' }, body: '### Your ORCID iD\n\n' + ID + '\n\n### Your DOI (optional)\n\n_No response_\n\n### What happened\n\nPLANTED\n' } }));
  const e5 = await runOn(ev({ issue: { labels: [{ name: 'bug' }], user: { login: 'alice' }, body: '### Your ORCID iD\n\n' + ID + '\n\n### Your DOI (optional)\n\n10.5555/own\n\n### What happened\n\nPLANTED\n' } }));
  const e6 = await runOn(ev({ issue: { labels: [{ name: 'bug' }], user: { login: 'alice' }, body: '### Your ORCID iD\n\n' + ID + '\n\n### What happened\n\nPLANTED\n' } }), down);
  t('identity events: another account is closed, the own iD and DOI are labelled "identity verified", a service down leaves it open as not checked', e4.closed && e5.labels.includes(LABELS.identity) && !e5.closed && !e6.closed && e6.labels.includes(LABELS.notChecked) && ![e4, e5, e6].some((r) => r.leak));
  fs.rmSync(root, { recursive: true, force: true });
  for (const [name, ok] of results) console.log((ok ? '  OK    ' : '  FAIL  ') + name);
  const failed = results.filter((r) => !r[1]).length;
  console.log((results.length - failed) + ' passed, ' + failed + ' failed' + (havePdf ? '' : ' (pdftotext missing: the PDF case was not run)') + '.');
  return failed === 0;
}

module.exports = { run, applies, jstDay, MARK, LABELS, LEGAL, ownWords, legalRequest, parseForm, field, normalise, quoteOf, htmlText, markdownText, readings, resolveLocation, checkQuote, orcidOk, linksGithub, orcidUrls, creatorIds, checkIdentity, TEXTS, AGAIN, commentFor, actionFor, specFor, loadConf, configProblems, fixturePdf, selfTest, QUOTE_MIN, QUOTE_MAX };

if (require.main === module) {
  const arg = process.argv[2];
  if (arg === '--test') selfTest().then((ok) => process.exit(ok ? 0 : 1));
  else if (arg === '--check') { const bad = configProblems(loadConf()); bad.forEach((b) => console.log('  FAIL  ' + b)); console.log(bad.length ? bad.length + ' problems.' : 'config.json: no problem.'); process.exit(bad.length ? 1 : 0); }
  else main().catch((e) => { console.error(e.message); process.exit(1); });
}
