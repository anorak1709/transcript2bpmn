// API key management for the caller's organization. Same key storage as the editor.
const $ = (id) => document.getElementById(id);
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

async function api(method, path, body, retried = false) {
  const headers = { Authorization: `Bearer ${apiKey(retried)}` };
  if (body) headers['Content-Type'] = 'application/json';
  const res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  if (res.status === 401 && !retried) return api(method, path, body, true);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `HTTP ${res.status}`);
  return data;
}

const cell = (text, cls) => { const td = document.createElement('td'); td.textContent = text; if (cls) td.className = cls; return td; };

async function load() {
  $('error').textContent = '';
  const keys = await api('GET', '/keys');
  const body = $('keys'); body.replaceChildren();
  for (const k of keys) {
    const tr = document.createElement('tr');
    const status = k.revoked_at ? `revoked ${new Date(k.revoked_at).toLocaleDateString()}` : (k.current ? 'active (this browser)' : 'active');
    tr.append(cell(k.name), cell(`t2b_${k.prefix}_…`), cell(new Date(k.created_at).toLocaleDateString()), cell(status, k.revoked_at ? 'revoked' : ''));
    const action = document.createElement('td');
    if (!k.revoked_at) {
      const b = document.createElement('button');
      b.textContent = 'Revoke';
      b.onclick = async () => {
        if (!confirm(`Revoke "${k.name}"? Anything using it stops working immediately.`)) return;
        try { await api('DELETE', `/keys/${k.id}`); await load(); } catch (e) { $('error').textContent = e.message; }
      };
      action.append(b);
    }
    tr.append(action);
    body.append(tr);
  }
  const u = await api('GET', '/usage');
  $('usage').textContent = `${u.jobs_this_month} transcript(s) processed` +
    (u.monthly_jobs_quota != null ? ` of ${u.monthly_jobs_quota} allowed` : ' (no monthly limit)') +
    ` · rate limits: ${u.rate_limit_per_minute}/min, ${u.rate_limit_heavy_per_minute}/min for heavy calls`;
}

$('create').onsubmit = async (e) => {
  e.preventDefault();
  try {
    const k = await api('POST', '/keys', { name: $('name').value.trim() });
    $('new-key-value').textContent = k.key;
    $('new-key').hidden = false;
    $('name').value = '';
    await load();
  } catch (err) { $('error').textContent = err.message; }
};
$('copy').onclick = () => navigator.clipboard.writeText($('new-key-value').textContent).then(() => { $('copy').textContent = 'Copied'; });

load().catch((e) => { $('error').textContent = e.message; });
