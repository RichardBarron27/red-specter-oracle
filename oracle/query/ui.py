"""ORACLE conversational query UI."""

CHAT_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ORACLE — Research Assistant</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Courier New', monospace; background: #0A0A0A; color: #E0E0E0; display: flex; height: 100vh; }
.sidebar {
    width: 280px; background: #111; border-right: 1px solid #222;
    display: flex; flex-direction: column; flex-shrink: 0;
}
.sidebar-header { padding: 1rem; border-bottom: 1px solid #222; }
.sidebar-header h2 { color: #00C853; font-size: 0.9rem; letter-spacing: 0.2em; }
.session-list { flex: 1; overflow-y: auto; padding: 0.5rem; }
.session-item {
    padding: 0.6rem; cursor: pointer; border-radius: 4px;
    margin-bottom: 0.3rem; font-size: 0.8rem; color: #999;
}
.session-item:hover { background: #1A1A1A; }
.session-item.active { background: #1A3A1A; color: #00C853; }
.session-item .name { display: block; font-weight: bold; color: #E0E0E0; }
.session-item .meta { font-size: 0.7rem; }
.new-session { padding: 0.5rem; border-top: 1px solid #222; }
.new-session input {
    width: 100%; background: #1A1A1A; border: 1px solid #333;
    color: #E0E0E0; padding: 0.5rem; font-family: inherit; font-size: 0.8rem;
}
.main { flex: 1; display: flex; flex-direction: column; }
.chat-header {
    padding: 0.8rem 1.5rem; border-bottom: 1px solid #1A1A1A;
    display: flex; justify-content: space-between; align-items: center;
}
.chat-header h3 { color: #00C853; font-size: 0.9rem; }
.chat-header .links a { color: #555; text-decoration: none; margin-left: 1rem; font-size: 0.8rem; }
.chat-header .links a:hover { color: #00C853; }
.messages { flex: 1; overflow-y: auto; padding: 1.5rem; }
.message { margin-bottom: 1.5rem; max-width: 800px; }
.message.user .bubble { background: #1A2A1A; border: 1px solid #2A3A2A; padding: 0.8rem 1rem; border-radius: 8px; }
.message.assistant .bubble {
    background: #1A1A1A; border: 1px solid #222; padding: 1rem;
    border-radius: 8px; line-height: 1.6;
}
.message .role { font-size: 0.7rem; color: #555; margin-bottom: 0.3rem; text-transform: uppercase; }
.confidence-bar {
    display: flex; gap: 1rem; margin-top: 0.8rem; padding-top: 0.6rem;
    border-top: 1px solid #222; font-size: 0.75rem;
}
.conf-item { display: flex; align-items: center; gap: 0.3rem; }
.conf-label { color: #666; }
.conf-value { font-weight: bold; }
.conf-value.high { color: #00C853; }
.conf-value.medium { color: #FFB300; }
.conf-value.low { color: #FF5252; }
.review-flag {
    background: #3A2A00; color: #FFB300; padding: 0.3rem 0.6rem;
    border-radius: 3px; font-size: 0.7rem; display: inline-block; margin-top: 0.5rem;
}
.citations {
    margin-top: 0.6rem; font-size: 0.75rem; color: #666;
    cursor: pointer; user-select: none;
}
.citations summary { color: #555; }
.citations .cite-item { padding: 0.2rem 0; border-bottom: 1px solid #111; }
.cite-source { color: #00C853; }
.input-area {
    padding: 1rem 1.5rem; border-top: 1px solid #1A1A1A;
    display: flex; gap: 0.5rem;
}
.input-area input {
    flex: 1; background: #1A1A1A; border: 1px solid #333;
    color: #E0E0E0; padding: 0.8rem 1rem; font-family: inherit;
    font-size: 0.9rem; border-radius: 4px;
}
.input-area input:focus { outline: none; border-color: #00C853; }
.input-area button {
    background: #00C853; color: #0A0A0A; border: none;
    padding: 0.8rem 1.5rem; font-family: inherit; font-weight: bold;
    cursor: pointer; border-radius: 4px;
}
.input-area button:hover { background: #00E676; }
.input-area button:disabled { background: #333; cursor: not-allowed; }
.loading { color: #555; font-style: italic; }
.empty-state { color: #333; text-align: center; padding: 4rem; font-size: 1.1rem; }
</style>
</head>
<body>

<div class="sidebar">
    <div class="sidebar-header"><h2>SESSIONS</h2></div>
    <div class="session-list" id="session-list"></div>
    <div class="new-session">
        <input id="new-session-input" placeholder="New session name..." onkeydown="if(event.key==='Enter')createSession()">
    </div>
</div>

<div class="main">
    <div class="chat-header">
        <h3 id="session-name">ORACLE</h3>
        <div class="links">
            <a href="/">Documents</a>
            <a href="/graph">Graph</a>
        </div>
    </div>

    <div class="messages" id="messages">
        <div class="empty-state" id="empty-state">
            Select or create a session to start querying.
        </div>
    </div>

    <div class="input-area">
        <input id="query-input" placeholder="Ask a question about the target system..."
               onkeydown="if(event.key==='Enter'&&!event.shiftKey)submitQuery()" disabled>
        <button id="submit-btn" onclick="submitQuery()" disabled>ASK</button>
    </div>
</div>

<script>
const API = '/api/v1';
let currentSession = null;

async function loadSessions() {
    const resp = await fetch(`${API}/sessions`);
    const sessions = await resp.json();
    const list = document.getElementById('session-list');
    list.innerHTML = '';
    sessions.forEach(s => {
        const div = document.createElement('div');
        div.className = 'session-item' + (currentSession === s.session_id ? ' active' : '');
        div.innerHTML = `<span class="name">${s.name}</span><span class="meta">${s.status}</span>`;
        div.onclick = () => selectSession(s.session_id, s.name);
        list.appendChild(div);
    });
}

async function createSession() {
    const input = document.getElementById('new-session-input');
    const name = input.value.trim();
    if (!name) return;
    const resp = await fetch(`${API}/sessions`, {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({name}),
    });
    const session = await resp.json();
    input.value = '';
    await loadSessions();
    selectSession(session.session_id, name);
}

async function selectSession(sid, name) {
    currentSession = sid;
    document.getElementById('session-name').textContent = name;
    document.getElementById('query-input').disabled = false;
    document.getElementById('submit-btn').disabled = false;
    await loadSessions();
    await loadHistory();
}

async function loadHistory() {
    if (!currentSession) return;
    const resp = await fetch(`${API}/sessions/${currentSession}`);
    const session = await resp.json();
    const queries = await fetch(`${API}/sessions/${currentSession}/queries`).then(r => r.json());

    const msgs = document.getElementById('messages');
    const empty = document.getElementById('empty-state');
    if (empty) empty.style.display = queries.length ? 'none' : 'block';

    // Render in chronological order
    const sorted = [...queries].reverse();
    let html = '';
    for (const q of sorted) {
        html += renderUserMessage(q.query_text);
        if (q.response_text) {
            let meta = {};
            try { meta = JSON.parse(q.metadata || '{}'); } catch(e) {}
            let sources = [];
            try { sources = JSON.parse(q.sources || '[]'); } catch(e) {}
            html += renderAssistantMessage(q.response_text, q.confidence_score, sources, meta.requires_review, meta.query_type);
        }
    }
    msgs.innerHTML = html || '<div class="empty-state">No queries yet. Ask a question below.</div>';
    msgs.scrollTop = msgs.scrollHeight;
}

function renderUserMessage(text) {
    return `<div class="message user"><div class="role">You</div><div class="bubble">${escapeHtml(text)}</div></div>`;
}

function renderAssistantMessage(text, confidence, citations, needsReview, queryType) {
    const confClass = confidence >= 0.7 ? 'high' : confidence >= 0.5 ? 'medium' : 'low';
    let html = `<div class="message assistant"><div class="role">ORACLE${queryType ? ' ['+queryType+']' : ''}</div>`;
    html += `<div class="bubble">${formatResponse(text)}`;

    // Confidence bar
    html += `<div class="confidence-bar">`;
    html += `<div class="conf-item"><span class="conf-label">Confidence:</span> <span class="conf-value ${confClass}">${(confidence*100).toFixed(0)}%</span></div>`;
    html += `</div>`;

    if (needsReview) {
        html += `<div class="review-flag">REQUIRES REVIEW — low confidence or missing citations</div>`;
    }

    // Citations
    if (citations && citations.length) {
        html += `<details class="citations"><summary>${citations.length} source(s)</summary>`;
        citations.forEach(c => {
            html += `<div class="cite-item"><span class="cite-source">${c.source_file}</span>`;
            if (c.page) html += ` p.${c.page}`;
            if (c.relevance) html += ` (${(c.relevance*100).toFixed(0)}% match)`;
            html += `</div>`;
        });
        html += `</details>`;
    }

    html += `</div></div>`;
    return html;
}

function formatResponse(text) {
    // Basic formatting: citations, bullet points, paragraphs
    let html = escapeHtml(text);
    // Highlight citations
    html = html.replace(/\\[Source:\\s*([^\\]]+)\\]/g, '<span class="cite-source">[$1]</span>');
    // Paragraphs
    html = html.replace(/\\n\\n/g, '</p><p>');
    html = html.replace(/\\n/g, '<br>');
    return '<p>' + html + '</p>';
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

async function submitQuery() {
    if (!currentSession) return;
    const input = document.getElementById('query-input');
    const text = input.value.trim();
    if (!text) return;

    input.value = '';
    input.disabled = true;
    document.getElementById('submit-btn').disabled = true;

    const msgs = document.getElementById('messages');
    const empty = document.getElementById('empty-state');
    if (empty) empty.style.display = 'none';

    // Show user message
    msgs.innerHTML += renderUserMessage(text);
    msgs.innerHTML += '<div class="message assistant" id="loading"><div class="role">ORACLE</div><div class="bubble loading">Thinking...</div></div>';
    msgs.scrollTop = msgs.scrollHeight;

    try {
        const resp = await fetch(`${API}/sessions/${currentSession}/ask`, {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({query: text}),
        });
        const data = await resp.json();

        // Remove loading
        document.getElementById('loading')?.remove();

        msgs.innerHTML += renderAssistantMessage(
            data.response_text || 'No response',
            data.confidence?.overall || 0,
            data.citations || [],
            data.requires_review,
            data.query_type,
        );
        msgs.scrollTop = msgs.scrollHeight;
    } catch (e) {
        document.getElementById('loading')?.remove();
        msgs.innerHTML += renderAssistantMessage('Error: ' + e.message, 0, [], true, 'ERROR');
    }

    input.disabled = false;
    document.getElementById('submit-btn').disabled = false;
    input.focus();
}

loadSessions();
</script>
</body>
</html>"""
