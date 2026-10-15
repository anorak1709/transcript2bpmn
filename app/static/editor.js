// Process map editor: bpmn-js Modeler + side panel + chat. Served same-origin (strict CSP).
const mapId = location.pathname.split('/').pop();
const $ = (id) => document.getElementById(id);
const modeler = new BpmnJS({ container: '#canvas' });
let map = null;      // last server response
let dirty = false;   // local edits not yet saved
let loaded = false;

const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
function toast(msg) { const t = $('toast'); t.textContent = msg; t.style.display = 'block'; clearTimeout(toast.t); toast.t = setTimeout(() => t.style.display = 'none', 5000); }
function setDirty(v) { dirty = v; $('dirty').hidden = !v; $('save').disabled = !v; }
const modelId = (xmlId) => {   // Node_t1 -> t1 (our ids); editor-created ids stay as they are
  const ids = new Set(map.model.nodes.map(n => n.id));
  const stripped = xmlId.replace(/^Node_/, '');
  return ids.has(stripped) ? stripped : (ids.has(xmlId) ? xmlId : null);
};

const KEY = 't2b_api_key';
function apiKey(force) {
  let key = null;
  try { key = force ? null : localStorage.getItem(KEY); } catch {}
  if (!key) {
    key = (prompt('API key for this workspace (t2b_…):') || '').trim();
    try { if (key) localStorage.setItem(KEY, key); } catch {}
  }
  return key;
}

async function api(method, path, body, type = 'application/json', retried = false) {
  const headers = { Authorization: `Bearer ${apiKey(retried)}` };
  if (body) headers['Content-Type'] = type;
  const res = await fetch(path, { method, headers, body });
  if (res.status === 401 && !retried) return api(method, path, body, type, true);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail ? (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)) : `HTTP ${res.status}`);
  return data;
}

async function render(next) {
  map = next;
  const canvas = modeler.get('canvas');
  const viewbox = loaded ? canvas.viewbox() : null;
  const { warnings } = await modeler.importXML(map.bpmn_xml);
  if (warnings.length) console.warn('bpmn-js import warnings', warnings);
  if (viewbox) canvas.viewbox(viewbox); else canvas.zoom('fit-viewport');
  loaded = true;
  setDirty(false);
  document.title = $('title').textContent = map.model.name;
  $('version').textContent = `v${map.version}`;
  $('undo').disabled = !map.can_undo;
  $('diarization').hidden = map.diarization_available !== false;
  renderQuestions();
  renderErrors();
  showSelection(null);
}

function renderQuestions() {
  const list = $('questions'); list.replaceChildren();
  $('q-count').textContent = map.model.open_questions.length || '';
  if (!map.model.open_questions.length) list.append(el('li', 'muted', 'None.'));
  for (const q of map.model.open_questions) {
    const li = el('li', 'item' + (q.related_node_ids.length ? ' clickable' : ''), q.question);
    if (q.related_node_ids.length) li.onclick = () => select(q.related_node_ids[0]);
    if (q.id.startsWith('conflict_')) {
      const conflictId = q.id.slice('conflict_'.length);
      const conflict = (map.conflicts || []).find(c => c.id === conflictId);
      const resolve = async (e, option) => {
        e.stopPropagation();
        if (dirty) await save();
        try {
          await api('POST', `/conflicts/${conflictId}/resolve`, JSON.stringify({ option }));
          render(await api('GET', `/maps/${mapId}`));
          toast(option == null ? 'Marked resolved' : `Applied: ${conflict.options[option]}`);
        } catch (err) { toast(err.message); }
      };
      const actions = el('div'); actions.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;margin-top:6px';
      (conflict ? conflict.options : []).forEach((opt, i) => {
        const b = el('button', null, `Use: ${opt}`);
        b.onclick = (e) => resolve(e, i);
        actions.append(b);
      });
      const done = el('button', null, 'I fixed it myself');
      done.onclick = (e) => resolve(e, null);
      actions.append(done);
      li.append(actions);
    }
    list.append(li);
  }
}

function renderErrors() {
  const list = $('errors'); list.replaceChildren();
  $('e-count').textContent = map.errors.length || '';
  if (!map.errors.length) list.append(el('li', 'muted', 'No problems found.'));
  for (const e of map.errors) {
    const li = el('li', 'item issue' + (e.node_ids.length ? ' clickable' : ''), e.message);
    if (e.node_ids.length) li.onclick = () => select(e.node_ids[0]);
    list.append(li);
  }
}

function select(nodeId) {
  const element = modeler.get('elementRegistry').get('Node_' + nodeId) || modeler.get('elementRegistry').get(nodeId);
  if (!element) return toast(`Step ${nodeId} isn't on the diagram`);
  modeler.get('selection').select(element);
  modeler.get('canvas').scrollToElement(element);
}

function showSelection(element) {
  const box = $('selection'); box.replaceChildren();
  const node = element && map.model.nodes.find(n => n.id === modelId(element.id));
  if (!element || !node) {
    box.className = 'muted';
    box.textContent = element ? 'Not saved yet. Save to keep this step.' : 'Select a step to see where it came from.';
    return;
  }
  box.className = '';
  const head = el('div', null, node.name || '(unnamed)');
  head.style.fontWeight = '600';
  if (node.user_added) head.append(el('span', 'badge', 'added by you'));
  else if (node.confidence < 0.6) head.append(el('span', 'badge', `low confidence ${Math.round(node.confidence * 100)}%`));
  const lane = map.model.lanes.find(l => l.id === node.lane_id);
  box.append(head, el('div', 'muted', `${node.type.replace('_', ' ')} · ${lane ? lane.name : node.lane_id}`));
  const segs = new Map(map.segments.map(s => [s.segment_id, s]));
  if (!node.source_segment_ids.length) box.append(el('div', 'muted', 'No transcript source.'));
  for (const id of node.source_segment_ids) {
    const s = segs.get(id);
    if (!s) { box.append(el('div', 'quote muted', `${id}: source text no longer available (retention policy)`)); continue; }
    const q = el('div', 'quote');
    const ts = s.start_ts != null ? ` · ${Math.floor(s.start_ts / 60)}:${String(Math.floor(s.start_ts % 60)).padStart(2, '0')}` : '';
    q.append(el('div', 'who', `${s.speaker || 'Unknown'}${ts} · ${id}`), el('div', null, s.text));
    box.append(q);
  }
}

function log(text, cls) { const d = el('div', cls, text); $('log').append(d); d.scrollIntoView({ block: 'end' }); }

async function save() {
  const { xml } = await modeler.saveXML({ format: true });
  render(await api('PUT', `/maps/${mapId}/bpmn`, xml, 'application/xml'));
  toast('Saved');
}

modeler.on('commandStack.changed', () => setDirty(true));
modeler.on('selection.changed', ({ newSelection }) => showSelection(newSelection.length === 1 ? newSelection[0] : null));

$('save').onclick = () => save().catch(e => toast(`Save failed: ${e.message}`));
$('undo').onclick = async () => {
  if (dirty && !confirm('Discard your unsaved changes and undo the last saved edit?')) return;
  try { render(await api('POST', `/maps/${mapId}/undo`)); toast('Undone'); } catch (e) { toast(e.message); }
};
$('download').onclick = async () => {
  const { xml } = await modeler.saveXML({ format: true });
  const a = el('a'); a.href = URL.createObjectURL(new Blob([xml], { type: 'application/xml' }));
  a.download = `${map.model.name.replace(/[^\w-]+/g, '_')}.bpmn`; a.click();
};
$('instruction').addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('chat-form').requestSubmit(); } });
$('chat-form').onsubmit = async (e) => {
  e.preventDefault();
  const instruction = $('instruction').value.trim();
  if (!instruction) return;
  $('send').disabled = true;
  log(instruction, 'me');
  try {
    if (dirty) await save();   // chat edits apply to the saved model; don't lose local changes
    const res = await api('POST', `/maps/${mapId}/chat`, JSON.stringify({ instruction }));
    log(res.reply || (res.ops.length ? 'Done.' : 'No changes.'));
    $('instruction').value = '';
    render(res);
  } catch (err) {
    log(err.message, 'err');
  } finally {
    $('send').disabled = false;
  }
};

(async () => {
  try {
    await render(await api('GET', `/maps/${encodeURIComponent(mapId)}`));
    const pre = new URLSearchParams(location.search).get('select');
    if (pre) select(pre);
  } catch (e) {
    $('title').textContent = 'Could not load map';
    toast(e.message);
  }
})();
