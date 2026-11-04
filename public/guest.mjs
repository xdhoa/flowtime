// Public (no sign-in) request flow: submit a request, then follow it with a private tracking link.
// Only the manager signs in. The tracking token lives in the URL fragment (#track=...), which
// browsers never send to the server in requests or Referer headers.
import {STATUSES} from './planner.mjs';
import {demoGuestAPI} from './demo.mjs';
import {SAVED_KEY, MAX_SAVED, escapeHTML, normalizeSaved, upsertSaved, parseTrackLink, isLate, deadlineOf, summarize, filterItems, sortItems, loadAll} from './requests.mjs';

const $ = id => document.getElementById(id);
const esc = escapeHTML;
const fmt = v => v ? new Date(v).toLocaleString('vi-VN', {day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit'}) : 'Chưa xác nhận';
const inputDate = v => { const d = new Date(v || Date.now() + 86400000); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16); };
const CATEGORIES = ['Proposal & kế hoạch', 'Truyền thông', 'Sự kiện', 'Nghiên cứu', 'Báo cáo', 'Thiết kế', 'Khác'];
const SAVED = SAVED_KEY;
// Only these fields of a tracked task are ever rendered in the workspace (mirrors PUBLIC_TASK_FIELDS).
const PUBLIC_FIELDS = ['id', 'title', 'category', 'requested_deadline', 'committed_deadline', 'status', 'created_at', 'updated_at'];
const pick = t => t ? Object.fromEntries(PUBLIC_FIELDS.map(k => [k, t[k] ?? null])) : null;

let ctx = {config: {}, toast: () => {}};
let chat = [];

export function setupGuest(options) { ctx = options; }
const isDemo = () => !ctx.config.configured;

async function call(path, body) {
  if (isDemo()) return demoGuestAPI(path, body);
  const r = await fetch('/api/index?route=' + encodeURIComponent(path), {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
  });
  const result = await r.json().catch(() => ({error: 'Không đọc được phản hồi máy chủ.'}));
  if (!r.ok) throw Error(result.error || 'Yêu cầu không thành công.');
  return result;
}

async function perform(button, fn) {
  const old = button?.textContent;
  if (button) { button.disabled = true; button.textContent = 'Đang xử lý…'; }
  try { return await fn(); } catch (e) { ctx.toast(e.message); } finally { if (button) { button.disabled = false; button.textContent = old; } }
}

// Requests sent from this device, so people can find them again without an account.
function readSaved() { try { return normalizeSaved(JSON.parse(localStorage.getItem(SAVED))); } catch { return []; } }
function writeSaved(list) { try { localStorage.setItem(SAVED, JSON.stringify(normalizeSaved(list))); } catch {} }
const mySaved = () => readSaved().filter(x => !!x.demo === isDemo());

// Use the public address (APP_URL) so saved links never point at a private preview URL.
function publicOrigin() { try { return ctx.config.appURL ? new URL(ctx.config.appURL).origin : location.origin; } catch { return location.origin; } }
const trackLink = token => `${publicOrigin()}/#track=${token}`;

function badge(t) {
  const late = isLate(t);
  return `<span class="badge ${late || t.status === 'declined' ? 'red' : t.status === 'delivered' ? 'green' : t.status === 'waiting' || t.status === 'review' ? 'amber' : ''}">${late ? 'Quá hạn · ' : ''}${esc(STATUSES[t.status] || t.status)}</span>`;
}

function shell(content, section = 'request', scroll = true) {
  $('loginView').hidden = true;
  $('appView').hidden = true;
  $('guestView').hidden = false;
  $('guestDemoBanner').hidden = !isDemo();
  document.querySelectorAll('[data-guest-nav]').forEach(a => {
    const on = a.dataset.guestNav === section;
    a.classList.toggle('active', on);
    if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
  $('guestContent').innerHTML = content;
  if (scroll) window.scrollTo({top: 0});
}

// Routes: '#track=<token>' follow a request · '#my-requests' everything saved on this device ·
// '#request/<code>' send to that manager · otherwise ask for the code.
export function showGuest(hash = '') {
  const token = hash.startsWith('#track=') ? hash.slice(7) : '';
  if (token) return renderTrack(token);
  if (hash === '#my-requests') return renderWorkspace();
  const code = hash.startsWith('#request/') ? decodeURIComponent(hash.slice(9)).trim().toLowerCase() : '';
  if (code) return openManager(code);
  renderCodeEntry();
}

function savedHTML(saved) {
  return saved.length
    ? saved.slice(0, 5).map(x => `<div class="list-row"><span>${esc(x.title)}<br><small class="caption">${x.manager ? 'Gửi cho ' + esc(x.manager) + ' · ' : ''}${fmt(x.created_at)}</small></span><a href="#track=${esc(x.token)}">Theo dõi →</a></div>`).join('')
      + `<div class="actions"><a class="primary-link" href="#my-requests">Xem tất cả (${saved.length}) trong Yêu cầu của tôi →</a><button type="button" class="link" id="gForget">Xóa danh sách khỏi thiết bị này</button></div>`
    : '<p class="help">Chưa có. Đường dẫn theo dõi được lưu tại đây sau khi bạn gửi. Đã có đường dẫn? <a href="#my-requests">Thêm vào Yêu cầu của tôi</a>.</p>';
}

function bindForget(rerender) {
  if ($('gForget')) $('gForget').onclick = () => { writeSaved(readSaved().filter(x => !!x.demo !== isDemo())); rerender(); };
}

function renderCodeEntry(error = '') {
  shell(`<section class="page-heading"><div><span class="eyebrow">A CLEAR BRIEF, A BETTER START</span><h1>Gửi yêu cầu cho người quản lý</h1><p>Mỗi người quản lý có một đường link riêng để nhận việc. Nếu bạn chỉ có mã, hãy nhập mã bên dưới. Không cần tài khoản.</p></div></section>
  ${error ? `<div class="errorbox">${esc(error)}</div>` : ''}
  <div class="intake-grid">
    <section class="panel"><div class="panel-head"><h2>Nhập mã người quản lý</h2></div>
      <form id="gCodeForm" class="panel-body"><label for="gCode">Mã (ví dụ: ngoc-hoa)</label><input id="gCode" required maxlength="40" autocomplete="off" autocapitalize="none" spellcheck="false">
      ${isDemo() ? '<p class="help">Demo: dùng mã <b>demo</b>.</p>' : '<p class="help">Mã là phần cuối của link người quản lý gửi cho bạn, sau <b>#request/</b>.</p>'}
      <button class="primary full" type="submit">Tiếp tục →</button></form></section>
    <div class="stack">
      <section class="panel"><div class="panel-head"><h2>Yêu cầu bạn đã gửi trên thiết bị này</h2></div><div class="panel-body">${savedHTML(mySaved())}</div></section>
      <section class="panel"><div class="panel-body"><h3>Bạn là người quản lý?</h3><p class="help">Tạo tài khoản để có link nhận việc riêng, dashboard, roadmap và bấm giờ.</p><a class="primary-link" href="#login">Đăng nhập / Tạo tài khoản →</a></div></section>
    </div>
  </div>`);
  $('gCodeForm').onsubmit = e => { e.preventDefault(); location.hash = '#request/' + encodeURIComponent($('gCode').value.trim().toLowerCase()); };
  bindForget(() => renderCodeEntry());
}

async function openManager(code) {
  shell('<div class="loading">Đang mở biểu mẫu…</div>');
  try {
    const manager = await call('public/manager', {slug: code});
    renderIntake(manager);
  } catch (e) {
    renderCodeEntry(e.message);
  }
}

function renderIntake(manager) {
  const saved = mySaved();
  const aiReady = ctx.config.ai && !isDemo();
  shell(`<section class="page-heading"><div><span class="eyebrow">A CLEAR BRIEF, A BETTER START</span><h1>Gửi yêu cầu cho ${esc(manager.name)}</h1><p>Không cần tài khoản. Sau khi gửi, bạn nhận một đường dẫn riêng để theo dõi tiến độ, trao đổi và duyệt kết quả.</p></div><a href="#request">Không phải người này?</a></section>
  <div class="intake-grid">
    <section class="panel"><div class="panel-head"><h2>Thông tin yêu cầu</h2><span class="badge">Bạn xác nhận trước khi gửi</span></div>
      <form id="guestForm" class="panel-body">
        <div class="formrow"><div><label for="gName">Tên của bạn *</label><input id="gName" required maxlength="120" autocomplete="name"></div>
        <div><label for="gEmail">Email *</label><input id="gEmail" type="email" required maxlength="254" autocomplete="email" placeholder="you@company.com"></div></div>
        <div class="hp" aria-hidden="true"><label for="gWebsite">Website</label><input id="gWebsite" tabindex="-1" autocomplete="off"></div>
        <label for="gTitle">Đầu việc *</label><input id="gTitle" required maxlength="250" placeholder="Tên công việc cụ thể">
        <label for="gDescription">Mô tả công việc</label><textarea id="gDescription" maxlength="6000" placeholder="Bối cảnh, phạm vi, yêu cầu chính…"></textarea>
        <label for="gDeliverable">Kết quả mong muốn</label><textarea id="gDeliverable" maxlength="2000" placeholder="Ví dụ: Proposal 5 trang + bản tóm tắt 1 trang"></textarea>
        <div class="formrow"><div><label for="gDeadline">Deadline mong muốn *</label><input id="gDeadline" type="datetime-local" required></div>
        <div><label for="gCategory">Loại công việc</label><select id="gCategory">${CATEGORIES.map(x => `<option>${x}</option>`).join('')}</select></div></div>
        <label for="gCollab">Người cần phối hợp</label><input id="gCollab" maxlength="500" placeholder="Tên / bộ phận liên quan">
        <label for="gAttachment">Đường dẫn tài liệu</label><input id="gAttachment" type="url" maxlength="2000" placeholder="https://…">
        <p class="help">Quản lý sẽ xem xét và xác nhận deadline. Ngày giờ nhập theo múi giờ thiết bị của bạn. Email dùng để nhận bàn giao kết quả.</p>
        <button class="primary full" type="submit">Xác nhận gửi yêu cầu ↗</button>
      </form></section>
    <div class="stack">
      <section class="panel"><div class="panel-head"><h2>✧ Trợ lý tạo yêu cầu</h2><span class="badge">${aiReady ? 'Đã kết nối AI' : 'Chưa kết nối AI'}</span></div><div class="panel-body">
        ${aiReady ? `<div class="chat-log" id="gChatLog"><div class="chat-bubble">Mô tả công việc, kết quả bạn muốn nhận, deadline và người cần phối hợp. Mình sẽ điền bản nháp vào biểu mẫu để bạn xem lại.</div>${chat.map(c => `<div class="chat-bubble ${c.role === 'user' ? 'user' : ''}">${esc(c.text)}</div>`).join('')}</div>
        <form id="gChatForm" class="chat-input"><label for="gChatMessage">Tin nhắn của bạn</label><textarea id="gChatMessage" maxlength="3500" required placeholder="Ví dụ: Chuẩn bị proposal hợp tác trước 17h thứ Sáu…"></textarea><button class="primary full" type="submit">Phân tích & tạo bản nháp →</button></form>
        <p class="help">Chỉ nội dung bạn nhập ở đây được gửi cho AI. Không gửi tài liệu bí mật nếu chưa được phép.</p>`
        : '<p class="help">Bạn có thể điền trực tiếp biểu mẫu bên cạnh.</p>'}
      </div></section>
      <section class="panel"><div class="panel-head"><h2>Yêu cầu bạn đã gửi trên thiết bị này</h2></div><div class="panel-body">${savedHTML(saved)}</div></section>
    </div>
  </div>`);
  $('gDeadline').value = '';
  $('guestForm').onsubmit = e => {
    e.preventDefault();
    perform(e.submitter, async () => {
      const payload = {
        name: $('gName').value.trim(), email: $('gEmail').value.trim(), website: $('gWebsite').value,
        title: $('gTitle').value.trim(), description: $('gDescription').value, deliverable: $('gDeliverable').value,
        requested_deadline: new Date($('gDeadline').value).toISOString(), category: $('gCategory').value,
        collaborators: $('gCollab').value, attachment_url: $('gAttachment').value, manager: manager.slug,
      };
      const r = await call('public/tasks', payload);
      writeSaved(upsertSaved(readSaved(), {token: r.token, title: r.task.title, manager: r.manager, created_at: new Date().toISOString(), demo: isDemo()}));
      chat = [];
      renderSent(r.token, r.task.title, r.manager);
    });
  };
  bindForget(() => renderIntake(manager));
  if ($('gChatForm')) $('gChatForm').onsubmit = e => {
    e.preventDefault();
    perform(e.submitter, async () => {
      const msg = $('gChatMessage').value;
      const conversation = [...chat, {role: 'user', text: msg}].slice(-8).map(c => c.role + ': ' + c.text).join('\n');
      if (conversation.length > 8000) { ctx.toast('Cuộc trao đổi khá dài. Hãy rút gọn yêu cầu trước khi phân tích.'); return; }
      const r = await call('public/ai', {message: conversation, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone});
      const a = r.analysis;
      chat.push({role: 'user', text: msg}, {role: 'assistant', text: a.message + (a.questions?.length ? '\n' + a.questions.join('\n') : '')});
      $('gChatLog').innerHTML = '<div class="chat-bubble">Bản nháp chỉ được gửi khi bạn xác nhận.</div>' + chat.map(c => `<div class="chat-bubble ${c.role === 'user' ? 'user' : ''}">${esc(c.text)}</div>`).join('');
      $('gChatLog').scrollTop = $('gChatLog').scrollHeight;
      $('gChatMessage').value = '';
      for (const [key, id] of [['title', 'gTitle'], ['description', 'gDescription'], ['deliverable', 'gDeliverable'], ['collaborators', 'gCollab']]) if (a[key]) $(id).value = a[key];
      if (a.category && CATEGORIES.includes(a.category)) $('gCategory').value = a.category;
      if (a.deadline_iso && Number.isFinite(Date.parse(a.deadline_iso))) $('gDeadline').value = inputDate(a.deadline_iso);
      ctx.toast('Đã tạo bản nháp. Hãy kiểm tra và xác nhận deadline trước khi gửi.');
    });
  };
}

function renderSent(token, title, managerName) {
  const link = trackLink(token);
  shell(`<section class="page-heading"><div><span class="eyebrow">REQUEST SENT</span><h1>Đã gửi yêu cầu ✓</h1><p>“${esc(title)}” đã đến ${esc(managerName || 'người quản lý')}. Họ sẽ xem xét và xác nhận deadline.</p></div></section>
  <section class="panel"><div class="panel-body">
    <h3>Đường dẫn theo dõi riêng của bạn</h3>
    <p class="help">Lưu lại đường dẫn này để xem tiến độ, trao đổi và duyệt kết quả. Ai có đường dẫn đều xem được yêu cầu, vì vậy chỉ chia sẻ với người liên quan. Đường dẫn cũng được lưu trên trình duyệt này.</p>
    <div class="track-link"><input id="gLink" readonly value="${esc(link)}" aria-label="Đường dẫn theo dõi"><button id="gCopy" type="button">Sao chép</button></div>
    <div class="actions"><a class="primary-link" href="#track=${esc(token)}">Mở trang theo dõi →</a><a class="secondary-link" href="#my-requests">Xem tất cả yêu cầu của tôi</a><a href="${esc(location.hash || '#request')}" id="gAnother">Gửi yêu cầu khác</a></div>
    <p class="help">Đã lưu vào <b>Yêu cầu của tôi</b> trên trình duyệt này (${mySaved().length}/${MAX_SAVED}). Dùng máy khác? Dán đường dẫn trên vào mục “Thêm đường dẫn theo dõi”.</p>
  </div></section>`);
  // The address is unchanged after submitting, so clicking a same-address link would do nothing.
  $('gAnother').onclick = e => { e.preventDefault(); showGuest(location.hash); };
  $('gCopy').onclick = e => perform(e.currentTarget, async () => { await navigator.clipboard.writeText(link); ctx.toast('Đã sao chép đường dẫn.'); });
}

async function renderTrack(token) {
  shell('<div class="loading">Đang tải yêu cầu…</div>', 'my-requests');
  let data;
  try {
    data = await call('public/track', {token});
  } catch (e) {
    shell(`<div class="errorbox">${esc(e.message)}</div><div class="actions"><a href="#my-requests">← Yêu cầu của tôi</a><a href="#request">Gửi yêu cầu mới</a></div>`, 'my-requests');
    return;
  }
  const t = data.task;
  const saved = readSaved().find(x => x.token === token);
  // Keep the saved title current; shape and other fields stay as they were.
  if (saved && t.title && saved.title !== t.title) writeSaved(upsertSaved(readSaved(), {token, title: t.title}));
  shell(`<p class="crumb"><a href="#my-requests">← Yêu cầu của tôi</a></p><section class="page-heading"><div><span class="eyebrow">THEO DÕI YÊU CẦU</span><h1>${esc(t.title)}</h1><p>Gửi bởi ${esc(t.requester_name)} · ${fmt(t.created_at)}</p></div><div class="actions">${saved ? '' : '<button type="button" id="gSaveThis">Lưu vào Yêu cầu của tôi</button>'}<a href="#request">+ Gửi yêu cầu khác</a></div></section>
  ${t.status === 'review' ? '<div class="notice-ok"><b>Kết quả đã sẵn sàng.</b> Hãy xem phần “Kết quả bàn giao” và xác nhận hoàn tất, hoặc gửi phản hồi nếu cần chỉnh sửa.</div>' : ''}
  <div class="details-grid"><section>
    <div class="detail-section">${badge(t)}<dl><dt>Hạn mong muốn</dt><dd>${fmt(t.requested_deadline)}</dd><dt>Hạn cam kết</dt><dd>${fmt(t.committed_deadline)}</dd><dt>Loại việc</dt><dd>${esc(t.category)}</dd><dt>Phối hợp</dt><dd>${esc(t.collaborators || 'Chưa nhập')}</dd></dl>
      <h3>Mô tả</h3><p>${esc(t.description || 'Chưa có mô tả.')}</p><h3>Kết quả mong muốn</h3><p>${esc(t.deliverable || 'Chưa nhập.')}</p>
      ${t.attachment_url ? `<a href="${esc(t.attachment_url)}" target="_blank" rel="noopener noreferrer">Mở tài liệu tham khảo ↗</a>` : ''}</div>
    ${t.result ? `<div class="detail-section"><h3>Kết quả bàn giao</h3><p>${esc(t.result)}</p>${t.status === 'review' ? '<button class="primary" id="gAccept">Xác nhận hoàn tất ✓</button>' : ''}</div>` : ''}
  </section><section>
    <h3>Trao đổi & lịch sử</h3>
    <div>${data.events.map(e => `<div class="event"><strong>${esc(e.actor_name)}</strong><time>${fmt(e.created_at)}</time><p>${esc(e.body)}</p></div>`).join('')}</div>
    <form id="gCommentForm"><label for="gComment">Bổ sung / phản hồi / đề nghị đổi deadline</label><textarea id="gComment" maxlength="4000" required placeholder="Nhập nội dung trao đổi…"></textarea><button type="submit" class="full">Gửi trao đổi</button></form>
    <p class="help">Deadline cam kết do quản lý xác nhận. Muốn đổi deadline hoặc phạm vi, hãy gửi trao đổi ở đây.</p>
  </section></div>`, 'my-requests');
  $('gCommentForm').onsubmit = e => { e.preventDefault(); perform(e.submitter, async () => { await call('public/comment', {token, body: $('gComment').value}); await renderTrack(token); ctx.toast('Đã gửi trao đổi.'); }); };
  if ($('gAccept')) $('gAccept').onclick = e => perform(e.currentTarget, async () => { await call('public/accept', {token}); await renderTrack(token); ctx.toast('Đã xác nhận kết quả. Cảm ơn bạn!'); });
  if ($('gSaveThis')) $('gSaveThis').onclick = () => {
    if (readSaved().length >= MAX_SAVED) { ctx.toast(`Đã đạt tối đa ${MAX_SAVED} yêu cầu trên thiết bị này. Hãy gỡ bớt trong Yêu cầu của tôi.`); return; }
    writeSaved(upsertSaved(readSaved(), {token, title: t.title, manager: '', created_at: t.created_at, demo: isDemo()}));
    $('gSaveThis').remove();
    ctx.toast('Đã lưu vào Yêu cầu của tôi trên trình duyệt này.');
  };
}

// ---- Requester workspace (#my-requests): every request saved on THIS browser, in one place. ----
let ws = {items: [], query: '', group: 'all'};
const GROUPS = [['all', 'Tất cả'], ['active', 'Đang thực hiện'], ['review', 'Chờ bạn duyệt'], ['late', 'Quá hạn'], ['done', 'Đã hoàn tất'], ['declined', 'Đã từ chối'], ['unavailable', 'Không tải được']];

function trustedOrigins() { return [publicOrigin(), location.origin]; }

async function renderWorkspace() {
  const saved = mySaved();
  shell('<div class="loading">Đang tải các yêu cầu đã lưu…</div>', 'my-requests');
  ws.items = await loadAll(saved, async token => ({task: pick((await call('public/track', {token})).task)}));
  if (location.hash !== '#my-requests') return; // user navigated away while loading
  drawWorkspace();
}

function statCard(label, value, sub, group) {
  return `<button type="button" class="stat stat-btn${ws.group === group ? ' active' : ''}" data-ws-group="${group}" aria-pressed="${ws.group === group}"><span>${label}</span><strong>${value}</strong><small>${sub}</small></button>`;
}

function rowHTML(it) {
  const t = it.task, s = it.saved;
  if (!t) return `<article class="ws-row unavailable"><div class="ws-main"><b>${esc(s.title || 'Yêu cầu không xác định')}</b><div class="task-meta">${s.manager ? 'Gửi cho ' + esc(s.manager) + ' · ' : ''}${esc(it.error || 'Không tải được.')}</div></div><div class="ws-side"><span class="badge red">Không tải được</span><button type="button" class="link" data-ws-remove="${esc(s.token)}">Gỡ khỏi thiết bị</button></div></article>`;
  const late = isLate(t);
  return `<article class="ws-row${late ? ' late' : ''}${t.status === 'review' ? ' review' : ''}"><div class="ws-main"><a class="ws-title" href="#track=${esc(s.token)}">${esc(t.title || s.title)}</a>
    <div class="task-meta">${s.manager ? 'Quản lý: ' + esc(s.manager) : 'Quản lý: chưa rõ'} · ${esc(t.category || 'Khác')}<br>◷ ${t.committed_deadline ? 'Hạn cam kết' : 'Hạn mong muốn'}: ${fmt(deadlineOf(t))}${late ? ' · <b class="late-text">Đã quá hạn</b>' : ''}</div></div>
    <div class="ws-side">${badge(t)}<a class="${t.status === 'review' ? 'primary-link' : 'secondary-link'}" href="#track=${esc(s.token)}">${t.status === 'review' ? 'Xem & duyệt →' : 'Xem chi tiết →'}</a><button type="button" class="link" data-ws-remove="${esc(s.token)}">Gỡ</button></div></article>`;
}

function listHTML() {
  if (!ws.items.length) return '';
  const shown = sortItems(filterItems(ws.items, ws));
  return shown.map(rowHTML).join('') || '<div class="empty"><b>Không có yêu cầu phù hợp</b>Thử đổi bộ lọc hoặc từ khóa tìm kiếm.</div>';
}

function drawWorkspace(scroll = true) {
  const s = summarize(ws.items);
  const count = ws.items.length;
  shell(`<section class="page-heading"><div><span class="eyebrow">KHÔNG CẦN TÀI KHOẢN</span><h1>Yêu cầu của tôi</h1><p>Tất cả yêu cầu đã lưu trên <b>trình duyệt này</b>. Danh sách không đồng bộ sang thiết bị khác; hãy dán đường dẫn theo dõi để thêm.</p></div><div class="actions"><a class="primary-link" href="#request">+ Gửi yêu cầu mới</a><button type="button" id="wsReload">↻ Làm mới</button></div></section>
  ${count ? `<div class="stats">${statCard('Tổng yêu cầu', s.total, `Đã lưu ${count}/${MAX_SAVED}`, 'all')}${statCard('Đang thực hiện', s.active, s.late ? `${s.late} việc quá hạn` : 'Mới gửi, tiếp nhận, đang làm', 'active')}${statCard('Chờ bạn duyệt', s.review, 'Kết quả đã sẵn sàng', 'review')}${statCard('Đã hoàn tất', s.done, 'Đã bàn giao', 'done')}</div>` : ''}
  <div class="ws-grid"><section class="panel"><div class="panel-head"><h2 id="wsCount">${count ? 'Danh sách yêu cầu' : 'Chưa có yêu cầu nào trên thiết bị này'}</h2>
    ${count ? `<div class="toolbar"><label class="sr-only" for="wsSearch">Tìm kiếm</label><input id="wsSearch" type="search" placeholder="Tìm theo tên việc, quản lý…" value="${esc(ws.query)}"><label class="sr-only" for="wsFilter">Lọc trạng thái</label><select id="wsFilter">${GROUPS.map(([v, l]) => `<option value="${v}"${v === ws.group ? ' selected' : ''}>${l}</option>`).join('')}</select></div>` : ''}</div>
    <div id="wsList">${count ? listHTML() : `<div class="empty"><b>Bắt đầu bằng một yêu cầu</b>Sau khi bạn gửi yêu cầu, đường dẫn theo dõi riêng sẽ tự lưu ở đây để bạn xem tiến độ, trao đổi và duyệt kết quả.<div class="actions center"><a class="primary-link" href="#request">Gửi yêu cầu đầu tiên →</a></div></div>`}</div></section>
  <div class="stack"><section class="panel"><div class="panel-head"><h2>Thêm đường dẫn theo dõi</h2></div><form id="wsAddForm" class="panel-body"><label for="wsLink">Dán đường dẫn đã nhận (dạng ${esc(publicOrigin())}/#track=…)</label><input id="wsLink" required autocomplete="off" spellcheck="false" placeholder="${esc(publicOrigin())}/#track=…"><p id="wsAddError" class="field-error" role="alert" hidden></p><button class="primary full" type="submit">Kiểm tra & thêm</button><p class="help">Đường dẫn được kiểm tra với Flowtime trước khi lưu. Chỉ lưu trên trình duyệt này, tối đa ${MAX_SAVED} yêu cầu.</p></form></section>
    <section class="panel"><div class="panel-body"><h3>Quyền riêng tư</h3><p class="help">Mỗi đường dẫn theo dõi là một khóa bí mật: ai có nó đều xem được yêu cầu. Không chia sẻ công khai. Dùng máy chung? Hãy xóa danh sách sau khi dùng.</p>${count ? '<button type="button" class="link" id="gForget">Xóa toàn bộ danh sách khỏi thiết bị này</button>' : ''}</div></section></div></div>`, 'my-requests', scroll);
  bindWorkspace();
}

function drawList() { if ($('wsList')) $('wsList').innerHTML = listHTML(); }

function bindWorkspace() {
  if ($('wsSearch')) $('wsSearch').oninput = e => { ws.query = e.target.value; drawList(); };
  if ($('wsFilter')) $('wsFilter').onchange = e => { ws.group = e.target.value; drawWorkspaceKeepFocus('wsFilter'); };
  document.querySelectorAll('[data-ws-group]').forEach(b => b.onclick = () => { ws.group = ws.group === b.dataset.wsGroup ? 'all' : b.dataset.wsGroup; drawWorkspaceKeepFocus(); });
  $('wsReload').onclick = e => perform(e.currentTarget, renderWorkspace);
  $('wsList').onclick = e => {
    const b = e.target.closest('[data-ws-remove]');
    if (!b || !confirm('Gỡ yêu cầu này khỏi danh sách trên thiết bị? Yêu cầu vẫn tồn tại; bạn cần đường dẫn để mở lại.')) return;
    const token = b.dataset.wsRemove;
    writeSaved(readSaved().filter(x => x.token !== token));
    ws.items = ws.items.filter(it => it.saved.token !== token);
    drawWorkspace(false);
  };
  bindForget(() => { ws.items = []; drawWorkspace(); });
  $('wsAddForm').onsubmit = e => {
    e.preventDefault();
    const err = $('wsAddError');
    const fail = msg => { err.textContent = msg; err.hidden = false; $('wsLink').setAttribute('aria-invalid', 'true'); $('wsLink').focus(); };
    err.hidden = true; $('wsLink').removeAttribute('aria-invalid');
    const parsed = parseTrackLink($('wsLink').value, trustedOrigins());
    if (parsed.error) return fail(parsed.error);
    if (mySaved().some(x => x.token === parsed.token)) return fail('Yêu cầu này đã có trong danh sách.');
    if (readSaved().length >= MAX_SAVED) return fail(`Đã đạt tối đa ${MAX_SAVED} yêu cầu. Hãy gỡ bớt yêu cầu cũ trước.`);
    perform(e.submitter, async () => {
      let task;
      try { task = pick((await call('public/track', {token: parsed.token})).task); } catch (x) { fail(x.message || 'Không kiểm tra được đường dẫn.'); return; }
      writeSaved(upsertSaved(readSaved(), {token: parsed.token, title: task.title, manager: '', created_at: task.created_at, demo: isDemo()}));
      ws.items = [{saved: mySaved().find(x => x.token === parsed.token), task, error: ''}, ...ws.items];
      drawWorkspace();
      ctx.toast('Đã thêm vào Yêu cầu của tôi.');
    });
  };
}

function drawWorkspaceKeepFocus(id) { drawWorkspace(false); if (id && $(id)) $(id).focus(); }
