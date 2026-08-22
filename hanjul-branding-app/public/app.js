// 한줄 브랜딩 — 프런트엔드 (프로토타입)
const $ = (s) => document.querySelector(s);
const state = { token: null, name: '', history: [] };

// ── 로그인 ──
$('#login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const email = $('#email').value.trim();
  const btn = $('#login-btn'), msg = $('#login-msg');
  msg.textContent = ''; btn.disabled = true; btn.textContent = '확인 중…';
  try {
    const r = await fetch('/api/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    });
    const d = await r.json();
    if (!r.ok) { msg.textContent = d.error || '로그인에 실패했어요.'; return; }
    state.token = d.token; state.name = d.name;
    $('#period').textContent = `수강기간 ~ ${d.expiresAt}`;
    updateUsage(d.used, d.limit);
    $('#login-view').classList.add('hidden');
    $('#chat-view').classList.remove('hidden');
    greet(d.name);
  } catch { msg.textContent = '서버에 연결할 수 없어요.'; }
  finally { btn.disabled = false; btn.textContent = '입장하기'; }
});

function updateUsage(used, limit) {
  $('#usage').textContent = limit > 0 ? `사용 ${used}/${limit}회` : `사용 ${used}회`;
}

function greet(name) {
  addBubble('bot',
    `${name ? name + '님, ' : ''}반가워요. 저는 『한줄 브랜딩』이에요.\n\n` +
    `바로 카피부터 뽑아드릴 수도 있지만, 그러면 어디서나 보이는 뻔한 문구밖에 안 나와요. ` +
    `먼저 짧게 여쭤보면서 당신만의 무기를 캐낼게요.\n\n` +
    `그냥 한마디만 툭 던져 보세요 — "나, 이거 하고 싶어."`);
}

// ── 채팅 ──
const input = $('#input');
input.addEventListener('input', () => {
  input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 150) + 'px';
});
input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('#chat-form').requestSubmit(); }
});

$('#chat-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  addBubble('user', text);
  state.history.push({ role: 'user', content: text });
  input.value = ''; input.style.height = 'auto';
  const sendBtn = $('#send-btn'); sendBtn.disabled = true;
  const typing = addBubble('bot typing', '생각 중…');

  try {
    const r = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + state.token },
      body: JSON.stringify({ messages: state.history }),
    });
    const d = await r.json();
    typing.remove();
    if (!r.ok) { addBubble('bot', '⚠️ ' + (d.error || '오류가 발생했어요.')); return; }
    addBubble('bot', d.reply);
    state.history.push({ role: 'assistant', content: d.reply });
    updateUsage(d.used, d.limit);
    if (d.mock) $('#mock-note').classList.remove('hidden');
  } catch {
    typing.remove(); addBubble('bot', '⚠️ 서버에 연결할 수 없어요.');
  } finally { sendBtn.disabled = false; input.focus(); }
});

function addBubble(cls, text) {
  const el = document.createElement('div');
  el.className = 'bubble ' + cls;
  el.textContent = text;
  $('#messages').appendChild(el);
  $('#messages').scrollTop = $('#messages').scrollHeight;
  return el;
}

// ── Brand Core 내보내기 (대화 저장) ──
$('#export-btn').addEventListener('click', () => {
  if (!state.history.length) { alert('아직 저장할 내용이 없어요. 먼저 대화를 시작해 주세요.'); return; }
  const today = new Date().toISOString().slice(0, 10);
  let md = `# 한줄 브랜딩 — Brand Core 작업 기록\n> ${state.name} · ${today}\n\n`;
  for (const m of state.history)
    md += (m.role === 'user' ? '## 🙋 나\n' : '## 🧭 한줄 브랜딩\n') + m.content + '\n\n';
  const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `brand-core-${today}.md`;
  a.click();
  URL.revokeObjectURL(a.href);
});

// ── 나가기 ──
$('#logout-btn').addEventListener('click', async () => {
  try { await fetch('/api/logout', { method: 'POST', headers: { 'Authorization': 'Bearer ' + state.token } }); } catch {}
  location.reload();
});
