// Requester workspace helpers (no sign-in). Pure functions so they can be tested in Node.
// Tracking tokens are secrets: they stay in this browser's localStorage and are only ever sent
// in the POST body of public/track to this Flowtime origin, never in a query string.
import {CLOSED} from './planner.mjs';

export const SAVED_KEY = 'flowtime-my-requests';
export const MAX_SAVED = 100;
// Same shape the backend accepts (flowtime/api.py TOKEN_RE).
export const TOKEN_RE = /^[A-Za-z0-9_-]{30,100}$/;

export const escapeHTML = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

// Older saved items look like {token, title, manager, created_at, demo}. Keep that shape; drop anything malformed.
export function normalizeSaved(list) {
  if (!Array.isArray(list)) return [];
  const seen = new Set();
  const out = [];
  for (const x of list) {
    if (!x || typeof x.token !== 'string' || !TOKEN_RE.test(x.token) || seen.has(x.token)) continue;
    seen.add(x.token);
    out.push({token: x.token, title: String(x.title ?? ''), manager: x.manager ? String(x.manager) : '', created_at: x.created_at || null, demo: !!x.demo});
  }
  return out.slice(0, MAX_SAVED);
}

// Put `item` first (replacing an older copy with the same token, but keeping fields it does not override).
export function upsertSaved(list, item) {
  const old = normalizeSaved(list);
  const prev = old.find(x => x.token === item.token) || {};
  return normalizeSaved([{...prev, ...item}, ...old.filter(x => x.token !== item.token)]);
}

/** Accept only a Flowtime tracking link on a trusted origin: https://<trusted>/#track=<token>.
 * Returns {token} or {error}. */
export function parseTrackLink(input, trustedOrigins) {
  const value = String(input ?? '').trim();
  if (!value) return {error: 'Hãy dán đường dẫn theo dõi.'};
  let url;
  try { url = new URL(value); } catch { return {error: 'Đây không phải một đường dẫn hợp lệ.'}; }
  const trusted = new Set((trustedOrigins || []).filter(Boolean).map(o => { try { return new URL(o).origin; } catch { return ''; } }).filter(Boolean));
  if (!['https:', 'http:'].includes(url.protocol) || !trusted.has(url.origin)) return {error: 'Đường dẫn không thuộc Flowtime này. Chỉ thêm đường dẫn theo dõi của ' + [...trusted].join(', ') + '.'};
  if (url.search || (url.pathname !== '/' && url.pathname !== '')) return {error: 'Đường dẫn theo dõi phải có dạng ' + [...trusted][0] + '/#track=…'};
  if (!url.hash.startsWith('#track=')) return {error: 'Đường dẫn không chứa mã theo dõi (#track=…).'};
  const token = url.hash.slice(7);
  if (!TOKEN_RE.test(token)) return {error: 'Mã theo dõi trong đường dẫn không hợp lệ.'};
  return {token};
}

export const deadlineOf = t => t?.committed_deadline || t?.requested_deadline || null;
export function isLate(t, now = Date.now()) {
  const d = Date.parse(deadlineOf(t));
  return !!t && !CLOSED.includes(t.status) && Number.isFinite(d) && d < now;
}

// Groups used by the summary cards and the filter.
export function groupOf(t) {
  if (!t) return 'unavailable';
  if (t.status === 'review') return 'review';
  if (t.status === 'delivered') return 'done';
  if (t.status === 'declined') return 'declined';
  return 'active';
}

export function summarize(items, now = Date.now()) {
  const s = {total: items.length, active: 0, review: 0, done: 0, declined: 0, late: 0, unavailable: 0};
  for (const it of items) {
    s[groupOf(it.task)]++;
    if (isLate(it.task, now)) s.late++;
  }
  return s;
}

export function filterItems(items, {query = '', group = 'all'} = {}, now = Date.now()) {
  const q = query.trim().toLowerCase();
  return items.filter(it => {
    if (group === 'late' ? !isLate(it.task, now) : group !== 'all' && groupOf(it.task) !== group) return false;
    if (!q) return true;
    return [it.task?.title || it.saved.title, it.saved.manager, it.task?.category].join(' ').toLowerCase().includes(q);
  });
}

// Needs-attention first: awaiting your review, late, active by deadline, then closed / unavailable.
export function sortItems(items, now = Date.now()) {
  const rank = it => groupOf(it.task) === 'review' ? 0 : isLate(it.task, now) ? 1 : groupOf(it.task) === 'active' ? 2 : groupOf(it.task) === 'unavailable' ? 4 : 3;
  const when = it => Date.parse(deadlineOf(it.task)) || Infinity;
  return [...items].sort((a, b) => rank(a) - rank(b) || when(a) - when(b));
}

// Fetch tasks with limited concurrency. `fetchOne(token)` resolves to {task} or throws.
export async function loadAll(saved, fetchOne, concurrency = 4) {
  const results = new Array(saved.length);
  let next = 0;
  async function worker() {
    while (next < saved.length) {
      const i = next++;
      try { results[i] = {saved: saved[i], task: (await fetchOne(saved[i].token)).task || null, error: ''}; }
      catch (e) { results[i] = {saved: saved[i], task: null, error: e?.message || 'Không tải được.'}; }
    }
  }
  await Promise.all(Array.from({length: Math.min(concurrency, saved.length)}, worker));
  return results;
}
