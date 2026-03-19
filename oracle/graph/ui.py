"""ORACLE graph visualisation UI — force-directed graph."""

GRAPH_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ORACLE — Component Graph</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: 'Courier New', monospace;
    background: #0A0A0A;
    color: #E0E0E0;
    display: flex;
    height: 100vh;
}
.sidebar {
    width: 320px;
    background: #111;
    border-right: 1px solid #222;
    overflow-y: auto;
    padding: 1rem;
    flex-shrink: 0;
}
.sidebar h2 { color: #00C853; font-size: 1rem; margin-bottom: 1rem; }
.session-select {
    width: 100%;
    background: #1A1A1A;
    border: 1px solid #333;
    color: #E0E0E0;
    padding: 0.5rem;
    font-family: inherit;
    margin-bottom: 1rem;
}
.btn {
    background: #00C853;
    color: #0A0A0A;
    border: none;
    padding: 0.5rem 1rem;
    cursor: pointer;
    font-family: inherit;
    font-weight: bold;
    width: 100%;
    margin-bottom: 0.5rem;
}
.btn:hover { background: #00E676; }
.btn.secondary { background: #333; color: #E0E0E0; }
.btn.secondary:hover { background: #444; }
.stats { margin: 1rem 0; }
.stat-row { display: flex; justify-content: space-between; padding: 0.3rem 0; border-bottom: 1px solid #1A1A1A; }
.stat-label { color: #666; }
.stat-value { color: #00C853; font-weight: bold; }
.detail-panel {
    margin-top: 1rem;
    background: #1A1A1A;
    padding: 0.8rem;
    border-radius: 4px;
    display: none;
}
.detail-panel h3 { color: #00C853; margin-bottom: 0.5rem; font-size: 0.9rem; }
.detail-row { font-size: 0.8rem; padding: 0.2rem 0; }
.detail-key { color: #666; }
.detail-value { color: #E0E0E0; }
.canvas-container {
    flex: 1;
    position: relative;
}
canvas {
    width: 100%;
    height: 100%;
    cursor: grab;
}
canvas:active { cursor: grabbing; }
.legend {
    position: absolute;
    bottom: 1rem;
    right: 1rem;
    background: rgba(17,17,17,0.9);
    padding: 0.8rem;
    border-radius: 4px;
    font-size: 0.75rem;
}
.legend-item {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.15rem 0;
}
.legend-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
}
</style>
</head>
<body>
<div class="sidebar">
    <h2>ORACLE GRAPH</h2>
    <select class="session-select" id="session-select">
        <option value="">Select session...</option>
    </select>
    <button class="btn" onclick="buildGraph()">BUILD GRAPH</button>
    <button class="btn secondary" onclick="extractComponents()">EXTRACT COMPONENTS</button>
    <button class="btn secondary" onclick="mapRelationships()">MAP RELATIONSHIPS</button>

    <div class="stats" id="stats">
        <div class="stat-row"><span class="stat-label">Components</span><span class="stat-value" id="s-nodes">0</span></div>
        <div class="stat-row"><span class="stat-label">Relationships</span><span class="stat-value" id="s-edges">0</span></div>
        <div class="stat-row"><span class="stat-label">Layers</span><span class="stat-value" id="s-layers">0</span></div>
    </div>

    <div class="detail-panel" id="detail-panel">
        <h3 id="detail-name">Component</h3>
        <div id="detail-content"></div>
    </div>
</div>

<div class="canvas-container">
    <canvas id="graph-canvas"></canvas>
    <div class="legend" id="legend"></div>
</div>

<script>
const API = '/api/v1';
let graphData = null;
let nodes = [];
let edges = [];
let selectedNode = null;
let dragNode = null;
let offsetX = 0, offsetY = 0;
let scale = 1;

const canvas = document.getElementById('graph-canvas');
const ctx = canvas.getContext('2d');

function resize() {
    canvas.width = canvas.parentElement.clientWidth * window.devicePixelRatio;
    canvas.height = canvas.parentElement.clientHeight * window.devicePixelRatio;
    ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
    draw();
}
window.addEventListener('resize', resize);

async function loadSessions() {
    const resp = await fetch(`${API}/sessions`);
    const sessions = await resp.json();
    const sel = document.getElementById('session-select');
    sel.innerHTML = '<option value="">Select session...</option>';
    sessions.forEach(s => {
        const opt = document.createElement('option');
        opt.value = s.session_id;
        opt.textContent = s.name;
        sel.appendChild(opt);
    });
}

async function extractComponents() {
    const sid = document.getElementById('session-select').value;
    if (!sid) return;
    const resp = await fetch(`${API}/graph/sessions/${sid}/extract?use_llm=false`, {method:'POST'});
    const data = await resp.json();
    alert(`Extracted ${data.components_extracted} components`);
}

async function mapRelationships() {
    const sid = document.getElementById('session-select').value;
    if (!sid) return;
    const resp = await fetch(`${API}/graph/sessions/${sid}/map-relationships`, {method:'POST'});
    const data = await resp.json();
    alert(`Mapped ${data.relationships_extracted} relationships`);
}

async function buildGraph() {
    const sid = document.getElementById('session-select').value;
    if (!sid) return;
    await fetch(`${API}/graph/sessions/${sid}/build`, {method:'POST'});
    const resp = await fetch(`${API}/graph/sessions/${sid}/data`);
    graphData = await resp.json();
    initGraph();
}

function initGraph() {
    if (!graphData) return;
    const w = canvas.parentElement.clientWidth;
    const h = canvas.parentElement.clientHeight;

    nodes = graphData.nodes.map((n, i) => ({
        ...n,
        x: w/2 + (Math.random()-0.5)*400,
        y: h/2 + (Math.random()-0.5)*400,
        vx: 0, vy: 0,
        radius: 12,
    }));

    edges = graphData.edges.map(e => ({
        ...e,
        sourceIdx: nodes.findIndex(n => n.id === e.source),
        targetIdx: nodes.findIndex(n => n.id === e.target),
    })).filter(e => e.sourceIdx >= 0 && e.targetIdx >= 0);

    document.getElementById('s-nodes').textContent = nodes.length;
    document.getElementById('s-edges').textContent = edges.length;
    document.getElementById('s-layers').textContent = Object.keys(graphData.stats?.by_layer || {}).length;

    buildLegend();
    simulate();
}

function buildLegend() {
    const types = new Set(nodes.map(n => n.component_type));
    const colours = {
        mcu:'#FF6B35', soc:'#FF6B35', fpga:'#FF6B35',
        memory:'#4ECDC4', sensor:'#45B7D1', ic:'#FFEAA7',
        protocol:'#6C5CE7', interface:'#00B894', firmware:'#A29BFE',
        os:'#FD79A8', software:'#E84393', other:'#B2BEC3',
        connector:'#96CEB4', power:'#E17055', bus:'#6C5CE7',
        passive:'#DFE6E9', driver:'#FDCB6E', library:'#E84393',
    };
    const legend = document.getElementById('legend');
    legend.innerHTML = '';
    types.forEach(t => {
        const div = document.createElement('div');
        div.className = 'legend-item';
        div.innerHTML = `<div class="legend-dot" style="background:${colours[t]||'#B2BEC3'}"></div>${t}`;
        legend.appendChild(div);
    });
}

function simulate() {
    for (let iter = 0; iter < 100; iter++) {
        // Repulsion
        for (let i = 0; i < nodes.length; i++) {
            for (let j = i+1; j < nodes.length; j++) {
                let dx = nodes[j].x - nodes[i].x;
                let dy = nodes[j].y - nodes[i].y;
                let d = Math.sqrt(dx*dx + dy*dy) || 1;
                let f = 5000 / (d * d);
                nodes[i].vx -= dx/d * f;
                nodes[i].vy -= dy/d * f;
                nodes[j].vx += dx/d * f;
                nodes[j].vy += dy/d * f;
            }
        }
        // Attraction along edges
        edges.forEach(e => {
            let s = nodes[e.sourceIdx], t = nodes[e.targetIdx];
            let dx = t.x - s.x, dy = t.y - s.y;
            let d = Math.sqrt(dx*dx + dy*dy) || 1;
            let f = (d - 120) * 0.01;
            s.vx += dx/d * f; s.vy += dy/d * f;
            t.vx -= dx/d * f; t.vy -= dy/d * f;
        });
        // Apply velocity with damping
        const w = canvas.parentElement.clientWidth;
        const h = canvas.parentElement.clientHeight;
        nodes.forEach(n => {
            n.vx *= 0.85; n.vy *= 0.85;
            n.x += n.vx; n.y += n.vy;
            n.x = Math.max(30, Math.min(w-30, n.x));
            n.y = Math.max(30, Math.min(h-30, n.y));
        });
    }
    draw();
}

function draw() {
    const w = canvas.parentElement.clientWidth;
    const h = canvas.parentElement.clientHeight;
    ctx.clearRect(0, 0, w, h);

    // Edges
    edges.forEach(e => {
        const s = nodes[e.sourceIdx], t = nodes[e.targetIdx];
        ctx.beginPath();
        ctx.moveTo(s.x, s.y);
        ctx.lineTo(t.x, t.y);
        ctx.strokeStyle = '#333';
        ctx.lineWidth = 1;
        ctx.stroke();
        // Label
        const mx = (s.x+t.x)/2, my = (s.y+t.y)/2;
        ctx.fillStyle = '#555';
        ctx.font = '9px monospace';
        ctx.fillText(e.relationship_type || '', mx, my-4);
    });

    // Nodes
    nodes.forEach(n => {
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.radius, 0, Math.PI*2);
        ctx.fillStyle = n.colour || '#B2BEC3';
        if (n === selectedNode) { ctx.lineWidth = 3; ctx.strokeStyle = '#00C853'; ctx.stroke(); }
        ctx.fill();
        // Label
        ctx.fillStyle = '#E0E0E0';
        ctx.font = '10px monospace';
        ctx.textAlign = 'center';
        ctx.fillText(n.name || '', n.x, n.y + n.radius + 14);
    });
}

canvas.addEventListener('click', e => {
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    selectedNode = null;
    for (const n of nodes) {
        const dx = mx - n.x, dy = my - n.y;
        if (dx*dx + dy*dy < n.radius*n.radius + 100) {
            selectedNode = n;
            showDetail(n);
            break;
        }
    }
    draw();
});

function showDetail(n) {
    const panel = document.getElementById('detail-panel');
    panel.style.display = 'block';
    document.getElementById('detail-name').textContent = n.name || 'Unknown';
    const fields = [
        ['Type', n.component_type], ['Part #', n.part_number],
        ['Manufacturer', n.manufacturer], ['Version', n.version],
        ['Layer', n.layer], ['Source', n.source_doc],
        ['Confidence', n.confidence],
    ];
    document.getElementById('detail-content').innerHTML = fields
        .filter(f => f[1])
        .map(f => `<div class="detail-row"><span class="detail-key">${f[0]}:</span> <span class="detail-value">${f[1]}</span></div>`)
        .join('');
}

resize();
loadSessions();
</script>
</body>
</html>"""
