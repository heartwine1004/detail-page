/*
 * 한줄 브랜딩 — 접속형 도구 웹앱 (프로토타입)
 * 의존성 없음: Node 18+ 만 있으면 `node server.js` 로 실행됩니다.
 *
 * 핵심 원칙: 프롬프트(한줄 브랜딩의 뇌)는 이 서버에만 있고,
 *           학생은 파일을 받지 않고 "접속"만 한다 → 수강기간이 끝나면 못 쓴다.
 *
 * 이 앱이 하는 일 (결제·회원가입은 라이브클래스가 담당하므로 여기엔 없음):
 *   1) 로그인       — 라이브클래스 수강생 명단(data/students.json)에 있는 이메일만 허용
 *   2) 수강기간 체크 — expiresAt(종료일)이 지나면 자동 잠금
 *   3) 채팅         — 서버가 Anthropic API로 클로드를 호출 (키·프롬프트는 서버에만)
 *   4) 사용량 상한   — 1인당 대화 횟수 제한(비용 방어)
 *   (Brand Core 내보내기는 프런트에서 대화 저장으로 처리)
 */

const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const PORT = process.env.PORT || 3000;
const MODEL = process.env.MODEL || 'claude-3-5-sonnet-latest'; // 배포 시 최신 모델로 교체 권장
const API_KEY = process.env.ANTHROPIC_API_KEY || '';           // 없으면 MOCK 모드로 동작
const ROOT = __dirname;

const SYSTEM_PROMPT = fs.readFileSync(path.join(ROOT, 'prompt', 'system-prompt.txt'), 'utf8');
const STUDENTS_PATH = path.join(ROOT, 'data', 'students.json');

// ── 유틸 ──────────────────────────────────────────────
const sessions = new Map(); // token -> email
const loadStudents = () => JSON.parse(fs.readFileSync(STUDENTS_PATH, 'utf8'));
const saveStudents = (list) => fs.writeFileSync(STUDENTS_PATH, JSON.stringify(list, null, 2));
const findStudent = (list, email) =>
  list.find((s) => s.email.toLowerCase() === String(email || '').trim().toLowerCase());
const isExpired = (s) => new Date() > new Date(s.expiresAt + 'T23:59:59');

function send(res, code, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(code, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(body);
}
function readBody(req) {
  return new Promise((resolve) => {
    let d = '';
    req.on('data', (c) => (d += c));
    req.on('end', () => { try { resolve(JSON.parse(d || '{}')); } catch { resolve({}); } });
  });
}
function authEmail(req) {
  const h = req.headers['authorization'] || '';
  const token = h.startsWith('Bearer ') ? h.slice(7) : '';
  return sessions.get(token) || null;
}

// ── 클로드 호출 (키 없으면 MOCK) ───────────────────────
async function callClaude(messages) {
  if (!API_KEY) {
    // MOCK 모드: 키 없이도 흐름을 시연할 수 있게 방법론에 맞는 안내 응답을 돌려준다.
    const lastUser = [...messages].reverse().find((m) => m.role === 'user');
    return (
      '『한줄 브랜딩』 (데모 모드) — 실제 API 키가 연결되면 여기서 진짜 코칭이 시작됩니다.\n\n' +
      '지금은 키가 없어 예시 응답이에요. 바로 카피부터 뽑지 않고, 먼저 여쭤볼게요.\n\n' +
      '① 지금 파시는 게 구체적으로 무엇인가요? (대상·형태·기간)\n' +
      '② 그분들은 이 전에 보통 무엇을 하고 있었나요?\n\n' +
      (lastUser ? `(입력하신 말: "${String(lastUser.content).slice(0, 60)}...")` : '')
    );
  }
  const r = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'x-api-key': API_KEY,
      'anthropic-version': '2023-06-01',
      'content-type': 'application/json',
    },
    body: JSON.stringify({ model: MODEL, max_tokens: 1500, system: SYSTEM_PROMPT, messages }),
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(`Anthropic ${r.status}: ${t.slice(0, 300)}`);
  }
  const j = await r.json();
  return (j.content || []).map((b) => b.text || '').join('').trim();
}

// ── 정적 파일 ──────────────────────────────────────────
const MIME = { '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8', '.woff2': 'font/woff2', '.svg': 'image/svg+xml' };
function serveStatic(req, res) {
  let p = decodeURIComponent(req.url.split('?')[0]);
  if (p === '/') p = '/index.html';
  const file = path.join(ROOT, 'public', path.normalize(p).replace(/^(\.\.[/\\])+/, ''));
  if (!file.startsWith(path.join(ROOT, 'public'))) { res.writeHead(403); return res.end(); }
  fs.readFile(file, (err, data) => {
    if (err) { res.writeHead(404); return res.end('Not found'); }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(file)] || 'application/octet-stream' });
    res.end(data);
  });
}

// ── 라우팅 ─────────────────────────────────────────────
const server = http.createServer(async (req, res) => {
  try {
    if (req.method === 'POST' && req.url === '/api/login') {
      const { email } = await readBody(req);
      const list = loadStudents();
      const s = findStudent(list, email);
      if (!s) return send(res, 403, { error: '등록되지 않은 이메일이에요. 라이브클래스에서 수강신청한 이메일로 로그인해 주세요.' });
      if (isExpired(s)) return send(res, 403, { expired: true, error: `수강기간이 종료되었어요 (종료일: ${s.expiresAt}). 재수강 시 다시 이용하실 수 있어요.` });
      const token = crypto.randomUUID();
      sessions.set(token, s.email);
      return send(res, 200, { token, name: s.name, expiresAt: s.expiresAt, used: s.used || 0, limit: s.limit || 0 });
    }

    if (req.method === 'POST' && req.url === '/api/chat') {
      const email = authEmail(req);
      if (!email) return send(res, 401, { error: '로그인이 필요해요.' });
      const list = loadStudents();
      const s = findStudent(list, email);
      if (!s || isExpired(s)) return send(res, 403, { expired: true, error: '수강기간이 종료되었어요.' });
      if ((s.limit || 0) > 0 && (s.used || 0) >= s.limit)
        return send(res, 429, { error: `이번 수강 사용량(${s.limit}회)을 모두 사용했어요.` });

      const { messages } = await readBody(req);
      const reply = await callClaude(Array.isArray(messages) ? messages : []);
      s.used = (s.used || 0) + 1; saveStudents(list);
      return send(res, 200, { reply, used: s.used, limit: s.limit || 0, mock: !API_KEY });
    }

    if (req.method === 'POST' && req.url === '/api/logout') {
      const h = req.headers['authorization'] || '';
      sessions.delete(h.startsWith('Bearer ') ? h.slice(7) : '');
      return send(res, 200, { ok: true });
    }

    if (req.method === 'GET') return serveStatic(req, res);
    send(res, 404, { error: 'not found' });
  } catch (e) {
    send(res, 500, { error: '서버 오류: ' + e.message });
  }
});

server.listen(PORT, () => {
  console.log(`한줄 브랜딩 도구 웹앱 → http://localhost:${PORT}`);
  console.log(API_KEY ? '· 실제 API 모드' : '· MOCK 모드 (ANTHROPIC_API_KEY 미설정 → 예시 응답)');
});
