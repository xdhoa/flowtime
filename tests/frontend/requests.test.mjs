import test from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
globalThis.crypto ??= webcrypto;
const store = new Map();
globalThis.localStorage = {getItem: k => store.get(k), setItem: (k, v) => store.set(k, v)};

const R = await import('../../public/requests.mjs');
const {resetDemo, demoAPI, demoGuestAPI} = await import('../../public/demo.mjs');

const TOK = 'A'.repeat(43);
const ORIGINS = ['https://flowtime.example.com', 'http://localhost:3000'];

test('parseTrackLink accepts only trusted Flowtime tracking links', () => {
  assert.deepEqual(R.parseTrackLink(`https://flowtime.example.com/#track=${TOK}`, ORIGINS), {token: TOK});
  assert.deepEqual(R.parseTrackLink(`  http://localhost:3000/#track=${TOK} `, ORIGINS), {token: TOK});
  for (const bad of ['', 'not a url', `https://evil.example/#track=${TOK}`, `https://flowtime.example.com.evil.io/#track=${TOK}`,
    `javascript:alert(1)//#track=${TOK}`, `https://flowtime.example.com/?track=${TOK}`, `https://flowtime.example.com/x#track=${TOK}`,
    'https://flowtime.example.com/#track=short', `https://flowtime.example.com/#track=${TOK}<script>`, 'https://flowtime.example.com/#request/demo']) {
    assert.ok(R.parseTrackLink(bad, ORIGINS).error, 'should reject: ' + bad);
  }
});

test('saved list keeps the old item shape, dedupes, drops junk and caps at 100', () => {
  const old = [{token: TOK, title: 'Poster', manager: 'Hòa', created_at: '2026-01-01T00:00:00Z', demo: false}, {token: TOK, title: 'dup'}, {token: 'bad'}, null, 5];
  assert.deepEqual(R.normalizeSaved(old), [{token: TOK, title: 'Poster', manager: 'Hòa', created_at: '2026-01-01T00:00:00Z', demo: false}]);
  assert.deepEqual(R.normalizeSaved('nope'), []);
  const many = Array.from({length: 130}, (_, i) => ({token: 'T'.repeat(40) + String(i).padStart(3, '0'), title: 't' + i}));
  assert.equal(R.normalizeSaved(many).length, R.MAX_SAVED);
  const up = R.upsertSaved(old, {token: TOK, title: 'Poster v2'});
  assert.equal(up.length, 1);
  assert.equal(up[0].title, 'Poster v2');
  assert.equal(up[0].manager, 'Hòa');
});

test('summary, late indicator, filter and sort', () => {
  const now = Date.parse('2026-06-01T12:00:00Z');
  const mk = (title, status, deadline, manager = '') => ({saved: {token: TOK, title, manager}, task: {title, status, requested_deadline: deadline, committed_deadline: null, category: 'Báo cáo'}});
  const items = [
    mk('Done', 'delivered', '2026-05-01T00:00:00Z'),
    mk('Late one', 'accepted', '2026-05-30T00:00:00Z', 'Hòa'),
    mk('Review me', 'review', '2026-05-01T00:00:00Z'),
    mk('Future', 'new', '2026-07-01T00:00:00Z'),
    {saved: {token: TOK, title: 'Gone'}, task: null, error: 'x'},
  ];
  assert.deepEqual(R.summarize(items, now), {total: 5, active: 2, review: 1, done: 1, declined: 0, late: 1, unavailable: 1});
  assert.equal(R.isLate(items[2].task, now), false, 'review is not late (waiting on requester)');
  assert.deepEqual(R.filterItems(items, {group: 'late'}, now).map(i => i.saved.title), ['Late one']);
  assert.deepEqual(R.filterItems(items, {query: 'hòa'}, now).map(i => i.saved.title), ['Late one']);
  assert.deepEqual(R.sortItems(items, now).map(i => i.saved.title), ['Review me', 'Late one', 'Future', 'Done', 'Gone']);
});

test('escapeHTML neutralises markup', () => {
  assert.equal(R.escapeHTML(`<img src=x onerror="a('b')">&`), '&lt;img src=x onerror=&quot;a(&#39;b&#39;)&quot;&gt;&amp;');
});

test('loadAll fetches every saved token via the demo public/track and isolates failures', async () => {
  resetDemo();
  const a = await demoGuestAPI('public/tasks', {manager: 'demo', name: 'Lan', email: 'l@x.co', title: 'A', requested_deadline: new Date(Date.now() + 864e5).toISOString()});
  const b = await demoGuestAPI('public/tasks', {manager: 'demo', name: 'Lan', email: 'l@x.co', title: 'B', requested_deadline: new Date(Date.now() + 864e5).toISOString()});
  await demoAPI(`tasks/${b.task.id}/plan`, {estimate_minutes: 30, priority: 2, committed_deadline: new Date().toISOString()}, true);
  await demoAPI(`tasks/${b.task.id}/status`, {status: 'review', result: 'ok'}, true);
  const saved = R.normalizeSaved([{token: a.token, title: 'A'}, {token: b.token, title: 'B'}, {token: 'Z'.repeat(40), title: 'Missing'}]);
  const items = await R.loadAll(saved, token => demoGuestAPI('public/track', {token}), 2);
  assert.deepEqual(items.map(i => i.task?.status ?? null), ['new', 'review', null]);
  assert.ok(items[2].error);
  assert.equal(R.summarize(items).review, 1);
});
