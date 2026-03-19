"""ORACLE intake UI — drag-and-drop file upload interface."""

INTAKE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ORACLE — Document Intake</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: 'Courier New', monospace;
    background: #0A0A0A;
    color: #E0E0E0;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
}
.header {
    text-align: center;
    padding: 2rem;
    border-bottom: 1px solid #1A1A1A;
    width: 100%;
}
.header h1 {
    color: #00C853;
    font-size: 1.8rem;
    letter-spacing: 0.3em;
}
.header .subtitle {
    color: #666;
    font-size: 0.85rem;
    margin-top: 0.5rem;
}
.container {
    max-width: 900px;
    width: 100%;
    padding: 2rem;
}
.session-bar {
    display: flex;
    gap: 1rem;
    margin-bottom: 2rem;
    align-items: center;
}
.session-bar select, .session-bar input, .session-bar button {
    background: #1A1A1A;
    border: 1px solid #333;
    color: #E0E0E0;
    padding: 0.6rem 1rem;
    font-family: inherit;
    font-size: 0.9rem;
}
.session-bar select { flex: 1; }
.session-bar input { flex: 1; }
.session-bar button {
    background: #00C853;
    color: #0A0A0A;
    border: none;
    cursor: pointer;
    font-weight: bold;
}
.session-bar button:hover { background: #00E676; }
.drop-zone {
    border: 2px dashed #333;
    border-radius: 8px;
    padding: 4rem 2rem;
    text-align: center;
    transition: all 0.3s;
    cursor: pointer;
    margin-bottom: 2rem;
}
.drop-zone.active {
    border-color: #00C853;
    background: rgba(0, 200, 83, 0.05);
}
.drop-zone h2 { color: #00C853; margin-bottom: 1rem; }
.drop-zone p { color: #666; font-size: 0.85rem; }
.file-input { display: none; }
.doc-list {
    border: 1px solid #1A1A1A;
    border-radius: 4px;
}
.doc-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.8rem 1rem;
    border-bottom: 1px solid #1A1A1A;
}
.doc-item:last-child { border-bottom: none; }
.doc-item .name { color: #00C853; }
.doc-item .meta { color: #666; font-size: 0.8rem; }
.doc-item .status { font-size: 0.8rem; padding: 0.2rem 0.6rem; border-radius: 3px; }
.status-received { background: #1A3A1A; color: #00C853; }
.status-error { background: #3A1A1A; color: #FF5252; }
.empty { color: #444; text-align: center; padding: 2rem; }
.stats {
    display: flex;
    gap: 2rem;
    margin-bottom: 2rem;
    justify-content: center;
}
.stat {
    text-align: center;
}
.stat .value { font-size: 1.5rem; color: #00C853; font-weight: bold; }
.stat .label { color: #666; font-size: 0.75rem; }
.toast {
    position: fixed;
    bottom: 2rem;
    right: 2rem;
    background: #1A3A1A;
    color: #00C853;
    padding: 1rem 1.5rem;
    border-radius: 4px;
    border: 1px solid #00C853;
    display: none;
    z-index: 100;
}
.toast.error { background: #3A1A1A; color: #FF5252; border-color: #FF5252; }
</style>
</head>
<body>

<div class="header">
    <h1>ORACLE</h1>
    <div class="subtitle">Offline Research Assistant for Component-Level Exploitation Analysis</div>
</div>

<div class="container">
    <div class="stats">
        <div class="stat"><div class="value" id="stat-sessions">0</div><div class="label">SESSIONS</div></div>
        <div class="stat"><div class="value" id="stat-docs">0</div><div class="label">DOCUMENTS</div></div>
        <div class="stat"><div class="value" id="stat-queries">0</div><div class="label">QUERIES</div></div>
    </div>

    <div class="session-bar">
        <select id="session-select"><option value="">Select session...</option></select>
        <input id="new-session-name" type="text" placeholder="New session name...">
        <button onclick="createSession()">NEW SESSION</button>
    </div>

    <div class="drop-zone" id="drop-zone" onclick="document.getElementById('file-input').click()">
        <h2>DROP FILES HERE</h2>
        <p>PDF, schematics, datasheets, images, source code, binary files</p>
        <p style="margin-top:0.5rem">or click to browse</p>
        <input type="file" id="file-input" class="file-input" multiple>
    </div>

    <div class="doc-list" id="doc-list">
        <div class="empty">No documents yet. Select or create a session, then drop files above.</div>
    </div>
</div>

<div class="toast" id="toast"></div>

<script>
const API = '/api/v1';
let currentSession = null;

async function loadSessions() {
    const resp = await fetch(`${API}/sessions`);
    const sessions = await resp.json();
    const sel = document.getElementById('session-select');
    sel.innerHTML = '<option value="">Select session...</option>';
    sessions.forEach(s => {
        const opt = document.createElement('option');
        opt.value = s.session_id;
        opt.textContent = `${s.name} (${s.session_id.slice(0,8)}...)`;
        sel.appendChild(opt);
    });
}

async function loadStats() {
    const resp = await fetch(`${API}/stats`);
    const data = await resp.json();
    document.getElementById('stat-sessions').textContent = data.database?.sessions || 0;
    document.getElementById('stat-docs').textContent = data.database?.documents || 0;
    document.getElementById('stat-queries').textContent = data.database?.queries || 0;
}

async function createSession() {
    const name = document.getElementById('new-session-name').value.trim();
    if (!name) { showToast('Enter a session name', true); return; }
    const resp = await fetch(`${API}/sessions`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name}),
    });
    const session = await resp.json();
    currentSession = session.session_id;
    document.getElementById('new-session-name').value = '';
    await loadSessions();
    document.getElementById('session-select').value = currentSession;
    await loadDocuments();
    await loadStats();
    showToast(`Session created: ${name}`);
}

async function loadDocuments() {
    if (!currentSession) {
        document.getElementById('doc-list').innerHTML = '<div class="empty">Select a session first.</div>';
        return;
    }
    const resp = await fetch(`${API}/sessions/${currentSession}/documents`);
    const docs = await resp.json();
    const list = document.getElementById('doc-list');
    if (docs.length === 0) {
        list.innerHTML = '<div class="empty">No documents in this session. Drop files above.</div>';
        return;
    }
    list.innerHTML = docs.map(d => `
        <div class="doc-item">
            <div>
                <span class="name">${d.filename}</span>
                <span class="meta">${d.file_type} &middot; ${(d.file_size/1024).toFixed(1)}KB</span>
            </div>
            <span class="status status-${d.ingestion_status}">${d.ingestion_status.toUpperCase()}</span>
        </div>
    `).join('');
}

async function uploadFile(file) {
    if (!currentSession) { showToast('Select or create a session first', true); return; }
    const formData = new FormData();
    formData.append('file', file);
    try {
        const resp = await fetch(`${API}/sessions/${currentSession}/documents`, {
            method: 'POST',
            body: formData,
        });
        if (!resp.ok) {
            const err = await resp.json();
            showToast(err.detail || 'Upload failed', true);
            return;
        }
        const doc = await resp.json();
        showToast(`Received: ${doc.filename}`);
        await loadDocuments();
        await loadStats();
    } catch (e) {
        showToast(`Upload error: ${e.message}`, true);
    }
}

function showToast(msg, isError = false) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.className = 'toast' + (isError ? ' error' : '');
    t.style.display = 'block';
    setTimeout(() => { t.style.display = 'none'; }, 3000);
}

// Drop zone
const dropZone = document.getElementById('drop-zone');
dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('active'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('active'));
dropZone.addEventListener('drop', e => {
    e.preventDefault();
    dropZone.classList.remove('active');
    Array.from(e.dataTransfer.files).forEach(uploadFile);
});
document.getElementById('file-input').addEventListener('change', e => {
    Array.from(e.target.files).forEach(uploadFile);
    e.target.value = '';
});

// Session selector
document.getElementById('session-select').addEventListener('change', e => {
    currentSession = e.target.value || null;
    loadDocuments();
});

// Init
loadSessions();
loadStats();
</script>
</body>
</html>"""
