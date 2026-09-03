"use strict";
/* joycon-patchbay — vanilla patch-panel client. Talks to the local engine over
   fetch (REST) + EventSource (live state). No build step, no dependencies. */

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

const api = {
  async get(p)      { const r = await fetch(p); if (!r.ok) throw await herr(r); return r.json(); },
  async send(m,p,b) { const r = await fetch(p, {method:m, headers:{'Content-Type':'application/json'},
                        body: JSON.stringify(b||{})}); if (!r.ok) throw await herr(r); return r.json(); },
  post(p,b){ return api.send('POST',p,b); },
  put (p,b){ return api.send('PUT', p,b); },
};
async function herr(r){ try { return new Error((await r.json()).error || r.statusText); }
                        catch { return new Error(r.statusText); } }

const S = {
  modules: [], nodeSpecs: {}, graph: {name:'', connections:[]},
  presets: [], presetName: '', panic: false, rate: 0,
  armed: null,                 // full source port id
  selected: null,              // connection id
  jacks: new Map(),            // full port id -> {el, portEl, meterEl, valEl, type, kind, moduleId}
  live: { ports:{}, sinks:{}, conns:{} },
  peak: {},
};

/* ------------------------------------------------------------------ boot */
init().catch(e => toast('startup: ' + e.message, true));
async function init(){
  const st = await api.get('/api/state');
  S.modules = st.modules; S.nodeSpecs = st.nodes;
  S.presets = st.presets; S.presetName = st.preset; S.rate = st.rate;
  S.graph = await api.get('/api/graph');

  $('#nodeType').innerHTML = Object.keys(S.nodeSpecs)
    .map(t => `<option value="${t}">${t}</option>`).join('');
  renderModules();
  syncPresetBar();
  wireBar();
  wireInspector();
  openStream();
  requestAnimationFrame(frame);
  addEventListener('resize', markCablesDirty);
  $('#patch').addEventListener('scroll', markCablesDirty, {passive:true});
  svg.addEventListener('click', e => {
    const id = e.target.getAttribute && e.target.getAttribute('data-id');
    if (id) selectConn(id);
  });
}

/* ------------------------------------------------------------ modules + jacks */
function renderModules(){
  const src = $('#srcMods'), sink = $('#sinkMods');
  src.replaceChildren(); sink.replaceChildren(); S.jacks.clear();
  for (const m of S.modules){
    (m.kind === 'source' ? src : sink).appendChild(moduleEl(m, m.kind));
  }
  markWired();
  markCablesDirty();
}

function moduleEl(m, kind){
  const el = document.createElement('div');
  el.className = 'module ' + (kind === 'source' ? 'src-mod' : 'sink-mod');
  const head = document.createElement('div');
  head.className = 'mh';
  head.innerHTML = `<span class="swatch"></span><span class="mname"></span><span class="mstatus"></span>`;
  $('.mname', head).textContent = m.label;
  $('.mstatus', head).textContent = m.status;
  el.appendChild(head);

  let lastGroup = null;
  for (const p of m.ports){
    if (p.group !== lastGroup){
      const g = document.createElement('div');
      g.className = 'grp-label'; g.textContent = p.group;
      el.appendChild(g); lastGroup = p.group;
    }
    el.appendChild(jackEl(m, p, kind));
  }
  return el;
}

function jackEl(m, p, kind){
  const full = `${m.id}/${p.id}`;
  const placeholder = p.id.includes('<');
  const j = document.createElement('div');
  j.className = 'jack' + (p.type === 'event' ? ' evt' : '') + (placeholder ? ' placeholder' : '');
  j.innerHTML =
    `<div class="jrow">` +
      `<span class="port"></span>` +
      `<span class="lbl"><span class="name"></span><span class="sub"></span></span>` +
      `<span class="val">${p.type === 'event' ? '○' : '–'}</span>` +
    `</div><span class="meter"><i></i></span>`;
  $('.name', j).textContent = p.label || p.id;
  $('.sub', j).textContent = placeholder ? (p.hint || '') : (p.unit || p.hint || '');
  if (!placeholder){
    j.addEventListener('click', () => onJack(full, kind));
    S.jacks.set(full, { el:j, portEl:$('.port', j), meterEl:$('.meter i', j),
                        valEl:$('.val', j), type:p.type, kind, moduleId:m.id });
  }
  return j;
}

/* --------------------------------------------------------------- patching */
function onJack(full, kind){
  if (kind === 'source'){
    S.armed = (S.armed === full) ? null : full;
    reflectArmed();
    hint(S.armed ? 'Now click a <b>sink</b> jack.' : null);
    return;
  }
  if (!S.armed){ toast('Arm a source jack first.', true); return; }
  const s = S.jacks.get(S.armed), d = S.jacks.get(full);
  const source = S.armed;
  api.post('/api/connect', { source, sink: full })
     .then(async () => {
        S.graph = await api.get('/api/graph');
        S.armed = null; reflectArmed(); markWired(); markCablesDirty();
        toast(s.type === 'scalar' && d.type === 'event'
              ? 'Patched — add a threshold / schmitt node to gate it.' : 'Patched.');
        selectConn(lastConnBetween(source, full));
     })
     .catch(e => toast(e.message, true));
}
function lastConnBetween(a,b){
  const m = S.graph.connections.filter(c => c.source===a && c.sink===b);
  return m.length ? m[m.length-1].id : null;
}
function reflectArmed(){
  for (const {el} of S.jacks.values()) el.classList.remove('armed','compatible');
  if (!S.armed) return;
  const s = S.jacks.get(S.armed); if (!s) { S.armed = null; return; }
  s.el.classList.add('armed');
  for (const {el,type,kind} of S.jacks.values()){
    if (kind === 'sink' && (type === s.type || s.type === 'event')) el.classList.add('compatible');
  }
}
function markWired(){
  const used = new Set();
  S.graph.connections.forEach(c => { used.add(c.source); used.add(c.sink); });
  for (const [full,{el}] of S.jacks) el.classList.toggle('wired', used.has(full));
}

/* ------------------------------------------------------------------ cables */
const svg = $('#cables');
function anchor(full){
  const j = S.jacks.get(full); if (!j) return null;
  // #cables is an absolutely-positioned child of the (position:relative) scroll
  // container, so its origin sits at the container's padding-box corner and it
  // scrolls with the content — add scrollLeft/Top to get content-space coords.
  const patch = $('#patch'), pr = patch.getBoundingClientRect();
  const r = j.portEl.getBoundingClientRect();
  return { x: r.left - pr.left + patch.scrollLeft + r.width/2,
           y: r.top  - pr.top  + patch.scrollTop  + r.height/2 };
}
/* Cables are rebuilt only when geometry could change (renderCables); the rAF loop
   just animates dash + activity on the existing path elements — cheap on a Pi. */
const cableEls = new Map();   // connId -> {vis, evt, enabled}
function renderCables(){
  const patch = $('#patch');
  const W = patch.scrollWidth, H = patch.scrollHeight;
  svg.setAttribute('width', W); svg.setAttribute('height', H);
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  const frag = document.createDocumentFragment();
  cableEls.clear();
  for (const c of S.graph.connections){
    const a = anchor(c.source), b = anchor(c.sink);
    if (!a || !b) continue;
    const dx = Math.min(Math.max(Math.abs(b.x - a.x) * 0.45, 42), 170);
    const d = `M ${a.x} ${a.y} C ${a.x+dx} ${a.y} ${b.x-dx} ${b.y} ${b.x} ${b.y}`;
    const st = S.jacks.get(c.source);
    const evt = !!(st && st.type === 'event');
    frag.appendChild(mk('path', {d, class:'hit', 'data-id':c.id}));
    const vis = mk('path', {
      d, fill:'none', 'data-id':c.id, 'stroke-linecap':'round',
      stroke: evt ? 'var(--out)' : 'var(--bridge)',
      'stroke-dasharray': evt ? '2 7' : '1 7',
    });
    frag.appendChild(vis);
    cableEls.set(c.id, { vis, evt, enabled: c.enabled !== false });
  }
  svg.replaceChildren(frag);
  animateCables();
}
function animateCables(){
  for (const [id, ce] of cableEls){
    const act = (S.live.conns[id] && S.live.conns[id].activity) || 0;
    const sel = S.selected === id;
    ce.vis.setAttribute('stroke-width', ((sel ? 3 : 1.4) + act * 3).toFixed(2));
    ce.vis.setAttribute('stroke-opacity', (ce.enabled ? 0.30 + act * 0.6 : 0.12).toFixed(2));
    ce.vis.setAttribute('stroke-dashoffset', (dashPhase * (0.5 + act * 4)).toFixed(1));
  }
}
function mk(tag, attrs){
  const e = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  return e;
}
let dashPhase = 0, cablesDirty = true;
function markCablesDirty(){ cablesDirty = true; }
function frame(){
  dashPhase -= 1;
  if (cablesDirty){ cablesDirty = false; renderCables(); }
  else animateCables();
  requestAnimationFrame(frame);
}

/* -------------------------------------------------------------- live stream */
function openStream(){
  const es = new EventSource('/events');
  es.onopen  = () => pill('#linkPill', 'ok',  'link');
  es.onerror = () => pill('#linkPill', 'bad', 'link');
  es.onmessage = ev => {
    let s; try { s = JSON.parse(ev.data); } catch { return; }
    S.live.ports = s.ports; S.live.sinks = s.sinks; S.live.conns = s.connections;
    S.panic = s.panic; S.rate = s.rate;
    if (s.preset && s.preset !== S.presetName){ S.presetName = s.preset; onPresetChangedExternally(); }
    paintMeters(); paintStatus();
  };
}
function paintMeters(){
  for (const [full, j] of S.jacks){
    const v = (j.kind === 'source' ? S.live.ports[full] : S.live.sinks[full]) ?? 0;
    if (j.type === 'event'){
      const on = v >= 0.5;
      j.valEl.textContent = on ? '●' : '○';
      j.meterEl.style.width = on ? '100%' : '0';
    } else {
      const a = Math.abs(v);
      const pk = S.peak[full] = Math.max(a, (S.peak[full] || 0.01) * 0.97, 0.01);
      j.valEl.textContent = fmt(v);
      j.meterEl.style.width = Math.min(100, (a / pk) * 100).toFixed(0) + '%';
    }
  }
}
function paintStatus(){
  $('#ratePill').textContent = `${Math.round(S.rate)} Hz`;
  const src = S.modules.find(m => m.kind === 'source');
  const snk = S.modules.find(m => m.kind === 'sink' && m.id === 'hid');
  pill('#srcPill',  !src ? 'bad' : (src.status === 'mock' ? 'mock' : 'ok'),
       src ? src.label : 'no source');
  pill('#sinkPill', !snk ? 'bad' : (/dry|unavail/.test(snk.status) ? 'warn' : 'ok'),
       snk ? snk.status : 'no sink');
  const pb = $('#panicBtn');
  pb.classList.toggle('armed', S.panic);
  pb.textContent = S.panic ? 'PANIC · ON' : 'PANIC';
}

/* --------------------------------------------------------------- inspector */
function selectConn(id){
  S.selected = id;
  const c = S.graph.connections.find(x => x.id === id);
  const insp = $('#inspector');
  if (!c){ insp.hidden = true; return; }
  insp.hidden = false;
  $('#inspTitle').textContent = `${short(c.source)}  →  ${short(c.sink)}`;
  $('#inspSub').textContent   = `${c.source}   →   ${c.sink}`;
  $('#inspEnabled').checked   = c.enabled !== false;
  renderChain(c);
}
function renderChain(c){
  const list = $('#chainList'); list.replaceChildren();
  if (!c.chain.length){
    const e = document.createElement('div');
    e.className = 'node empty'; e.textContent = 'pass-through — no transform';
    list.appendChild(e);
  }
  c.chain.forEach((n, i) => list.appendChild(nodeEl(c, n, i)));
}
function nodeEl(c, n, i){
  const spec = S.nodeSpecs[n.type] || {};
  n.params = n.params || {};
  const el = document.createElement('div'); el.className = 'node';
  const h = document.createElement('div'); h.className = 'nh';
  h.innerHTML = `<span class="nt"></span><span class="nord"></span>`;
  $('.nt', h).textContent = n.type;
  $('.nord', h).append(
    mkbtn('↑', () => moveNode(c, i, -1)),
    mkbtn('↓', () => moveNode(c, i, +1)),
    mkbtn('✕', () => { c.chain.splice(i, 1); pushChain(c); }),
  );
  el.appendChild(h);
  const entries = Object.entries(spec);
  if (entries.length){
    const params = document.createElement('div'); params.className = 'params';
    for (const [k, meta] of entries){
      const lab = document.createElement('label'); lab.textContent = k;
      let input;
      if (meta && meta.choices){
        input = document.createElement('select');
        input.innerHTML = meta.choices
          .map(o => `<option ${o === n.params[k] ? 'selected' : ''}>${o}</option>`).join('');
      } else {
        const [def,min,max,step] = meta;
        input = document.createElement('input');
        input.type = 'number'; input.step = step; input.min = min; input.max = max;
        input.value = (n.params[k] ?? def);
      }
      input.addEventListener('change', () => {
        n.params[k] = input.tagName === 'SELECT' ? input.value : parseFloat(input.value);
        pushChain(c);
      });
      lab.appendChild(input); params.appendChild(lab);
    }
    el.appendChild(params);
  }
  return el;
}
function mkbtn(txt, fn){ const b = document.createElement('button'); b.type = 'button';
  b.textContent = txt; b.addEventListener('click', fn); return b; }
function moveNode(c, i, dir){
  const j = i + dir; if (j < 0 || j >= c.chain.length) return;
  [c.chain[i], c.chain[j]] = [c.chain[j], c.chain[i]]; pushChain(c);
}
async function pushChain(c){
  try {
    await api.put('/api/connection', { id: c.id, chain: c.chain });
    S.graph = await api.get('/api/graph');
    selectConn(c.id);
  } catch(e){ toast(e.message, true); }
}
function wireInspector(){
  $('#inspClose').addEventListener('click', () => { S.selected = null; $('#inspector').hidden = true; });
  $('#inspEnabled').addEventListener('change', async e => {
    if (!S.selected) return;
    await api.put('/api/connection', { id: S.selected, enabled: e.target.checked });
    S.graph = await api.get('/api/graph');
  });
  $('#addNode').addEventListener('click', () => {
    const c = S.graph.connections.find(x => x.id === S.selected); if (!c) return;
    const t = $('#nodeType').value, spec = S.nodeSpecs[t] || {};
    const params = {};
    for (const [k, meta] of Object.entries(spec))
      params[k] = (meta && meta.choices) ? meta.choices[0] : meta[0];
    c.chain.push({ type: t, params }); pushChain(c);
  });
  $('#inspDelete').addEventListener('click', async () => {
    if (!S.selected) return;
    await api.post('/api/disconnect', { id: S.selected });
    S.selected = null; $('#inspector').hidden = true;
    S.graph = await api.get('/api/graph'); markWired(); markCablesDirty();
  });
}

/* ----------------------------------------------------------------- presets */
function wireBar(){
  $('#loadBtn').addEventListener('click', async () => {
    await api.post('/api/preset/load', { name: $('#presetSel').value });
    await reloadAll(); toast(`loaded ${S.presetName}`);
  });
  $('#saveBtn').addEventListener('click', async () => {
    await api.post('/api/preset/save', { name: S.presetName, graph: S.graph });
    toast(`saved ${S.presetName}`);
  });
  $('#saveAsBtn').addEventListener('click', async () => {
    const name = (prompt('Save preset as:', S.presetName + '-copy') || '').trim(); if (!name) return;
    await api.post('/api/preset/save', { name, graph: { ...S.graph, name } });
    await api.post('/api/preset/load', { name });
    await reloadAll(); toast(`saved ${name}`);
  });
  $('#newBtn').addEventListener('click', async () => {
    const name = (prompt('New empty preset name:') || '').trim(); if (!name) return;
    await api.post('/api/preset/save', { name, graph: { name, connections: [] } });
    await api.post('/api/preset/load', { name });
    await reloadAll(); toast(`new preset ${name}`);
  });
  $('#delBtn').addEventListener('click', async () => {
    const name = $('#presetSel').value;
    if (!confirm(`Delete preset "${name}"?`)) return;
    const r = await api.post('/api/preset/delete', { name });
    S.presets = r.presets; syncPresetBar(); toast(`deleted ${name}`);
  });
  $('#panicBtn').addEventListener('click', () => api.post('/api/panic', { on: !S.panic }));
}
async function reloadAll(){
  const st = await api.get('/api/state');
  S.modules = st.modules; S.presets = st.presets; S.presetName = st.preset;
  S.graph = await api.get('/api/graph');
  S.selected = null; S.armed = null; $('#inspector').hidden = true;
  renderModules(); syncPresetBar();
}
async function onPresetChangedExternally(){          // btn.home -> sys/preset.cycle
  S.graph = await api.get('/api/graph');
  const st = await api.get('/api/state');
  S.modules = st.modules;
  renderModules(); syncPresetBar();
  toast(`preset → ${S.presetName}`);
}
function syncPresetBar(){
  $('#presetSel').innerHTML = S.presets
    .map(n => `<option ${n === S.presetName ? 'selected' : ''}>${n}</option>`).join('');
}

/* ------------------------------------------------------------------- utils */
function short(full){ return full.split('/').slice(1).join('/'); }
function fmt(v){ const a = Math.abs(v);
  return a >= 100 ? v.toFixed(0) : a >= 1 ? v.toFixed(2) : v.toFixed(3); }
function pill(sel, cls, txt){
  const el = $(sel); if (!el) return;
  el.className = 'pill ' + cls;
  el.replaceChildren(document.createElement('i'), document.createTextNode(' ' + txt));
}
function hint(html){ $('#hint').innerHTML = html ||
  'Click a <b>source</b> jack, then a <b>sink</b> jack, to patch. Click a cable to shape it.'; }
let toastT;
function toast(msg, bad){
  const t = $('#toast'); t.textContent = msg; t.hidden = false;
  t.classList.toggle('bad', !!bad);
  clearTimeout(toastT); toastT = setTimeout(() => { t.hidden = true; }, 2400);
}
