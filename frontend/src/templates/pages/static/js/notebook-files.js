/**
 * Notebook volume browser — save/open/upload/download .ipynb in /data/notebooks/
 */

const nbState = {
  notebooks: [],
  lastSavedName: null,
  lastSavedAt: null,
};

function nbEscapeHtml(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function nbSetStatus(msg) {
  const el = document.getElementById('nb-status');
  if (el) el.textContent = msg || '';
}

function nbFormatRelativeTime(iso) {
  if (!iso) return '—';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '—';
  const diff = Date.now() - then;
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function nbUpdateCurrentMeta() {
  const nameEl = document.getElementById('nb-current-name');
  const savedEl = document.getElementById('nb-last-saved');
  const displayName = typeof window.getNotebookDisplayName === 'function'
    ? window.getNotebookDisplayName()
    : 'Notebook';
  if (nameEl) nameEl.textContent = displayName;
  if (savedEl) {
    if (nbState.lastSavedName && nbState.lastSavedAt) {
      savedEl.textContent = `Saved ${nbState.lastSavedName} · ${nbFormatRelativeTime(nbState.lastSavedAt)}`;
    } else {
      savedEl.textContent = 'Not saved to volume';
    }
  }
}

function nbJoinSource(source) {
  if (Array.isArray(source)) return source.join('');
  return source == null ? '' : String(source);
}

function nbParseSqlFence(text) {
  const trimmed = (text || '').trim();
  const m = trimmed.match(/^```(?:sql)?\s*\n([\s\S]*?)\n```$/i);
  if (m) return m[1];
  return null;
}

function ipynbToSporeState(nb, fileName) {
  const cells = (nb.cells || []).map((c, i) => {
    const source = nbJoinSource(c.source);
    const meta = c.metadata || {};
    if (c.cell_type === 'code') {
      return { id: `cell-import-${i}`, type: 'python', code: source };
    }
    if (meta.spore?.type === 'sql') {
      return { id: `cell-import-${i}`, type: 'sql', code: nbParseSqlFence(source) || source };
    }
    const sqlBody = nbParseSqlFence(source);
    if (sqlBody != null) {
      return { id: `cell-import-${i}`, type: 'sql', code: sqlBody };
    }
    return { id: `cell-import-${i}`, type: 'markdown', code: source };
  });

  const baseName = (fileName || '').replace(/\.ipynb$/i, '') || 'Imported Notebook';
  return {
    name: baseName,
    cell_counter: cells.length,
    cells,
  };
}

async function loadNotebooks() {
  const listEl = document.getElementById('nb-list');
  if (!listEl) return;
  nbSetStatus('Loading…');
  listEl.innerHTML = '<div class="text-[9px] text-slate-400 text-center py-8 font-bold">Loading…</div>';
  try {
    const res = await fetch('/api/notebooks');
    if (!res.ok) throw new Error('Failed to list notebooks');
    const data = await res.json();
    nbState.notebooks = data.notebooks || [];
    renderNotebookList();
    nbUpdateCurrentMeta();
    nbSetStatus('');
  } catch (e) {
    listEl.innerHTML = `<div class="text-[9px] text-red-400 text-center py-6 font-bold">${nbEscapeHtml(e.message)}</div>`;
    nbSetStatus('');
  }
}

function renderNotebookList() {
  const listEl = document.getElementById('nb-list');
  if (!listEl) return;
  const items = nbState.notebooks;
  if (!items.length) {
    listEl.innerHTML = `
      <div class="flex flex-col items-center justify-center py-12 opacity-40">
        <span class="material-symbols-outlined text-[32px] mb-2">note_stack</span>
        <span class="text-[10px] font-medium">No notebooks saved yet</span>
      </div>`;
    return;
  }

  listEl.innerHTML = items.map((nb) => {
    const selected = nbState.lastSavedName === nb.name;
    return `
      <div class="nb-row w-full flex items-center gap-2 rounded-xl border p-2.5 mb-1 transition-colors cursor-pointer
        ${selected ? 'border-primary/40 bg-primary-soft/30' : 'border-slate-200 hover:border-primary/30 bg-white'}"
        data-nb-name="${nbEscapeHtml(nb.name)}">
        <div class="w-8 h-8 rounded-pill bg-primary-soft border border-primary/20 flex items-center justify-center shrink-0">
          <span class="material-symbols-outlined text-primary text-[16px]">description</span>
        </div>
        <div class="flex-1 min-w-0">
          <p class="text-[10px] font-black text-slate-900 font-mono truncate">${nbEscapeHtml(nb.name)}</p>
          <p class="text-[8px] font-mono text-slate-400 mt-0.5">${nbEscapeHtml(nb.size_pretty || '')} · ${nbEscapeHtml(nbFormatRelativeTime(nb.modified))}</p>
        </div>
        <div class="flex items-center gap-0.5 shrink-0">
          <button type="button" class="nb-open-btn w-6 h-6 flex items-center justify-center rounded text-slate-400 hover:text-primary" title="Open" data-nb-open="${nbEscapeHtml(nb.name)}">
            <span class="material-symbols-outlined text-[14px]">open_in_new</span>
          </button>
          <button type="button" class="nb-dl-btn w-6 h-6 flex items-center justify-center rounded text-slate-400 hover:text-primary" title="Download" data-nb-dl="${nbEscapeHtml(nb.name)}">
            <span class="material-symbols-outlined text-[14px]">download</span>
          </button>
          <button type="button" class="nb-del-btn w-6 h-6 flex items-center justify-center rounded text-slate-400 hover:text-red-500" title="Delete" data-nb-del="${nbEscapeHtml(nb.name)}">
            <span class="material-symbols-outlined text-[14px]">delete</span>
          </button>
        </div>
      </div>`;
  }).join('');

  listEl.querySelectorAll('.nb-row').forEach((row) => {
    row.addEventListener('click', (e) => {
      if (e.target.closest('button')) return;
      const name = row.dataset.nbName;
      if (name) nbOpen(name);
    });
  });
  listEl.querySelectorAll('[data-nb-open]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      nbOpen(btn.dataset.nbOpen);
    });
  });
  listEl.querySelectorAll('[data-nb-dl]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      nbDownload(btn.dataset.nbDl);
    });
  });
  listEl.querySelectorAll('[data-nb-del]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      nbDelete(btn.dataset.nbDel);
    });
  });
}

function nbSafeFilename(name) {
  const base = (name || 'notebook').trim();
  return base.toLowerCase().endsWith('.ipynb') ? base : `${base}.ipynb`;
}

async function nbSaveCurrent() {
  if (typeof window.buildIpynb !== 'function') return;
  const displayName = typeof window.getNotebookDisplayName === 'function'
    ? window.getNotebookDisplayName()
    : 'notebook';
  const fileName = nbSafeFilename(displayName);
  nbSetStatus('Saving…');
  try {
    const res = await fetch('/api/notebooks/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: fileName, ipynb: window.buildIpynb() }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || 'Save failed');
    }
    const data = await res.json();
    nbState.lastSavedName = data.name || fileName;
    nbState.lastSavedAt = data.modified || new Date().toISOString();
    nbUpdateCurrentMeta();
    await loadNotebooks();
    nbSetStatus('Saved');
    setTimeout(() => nbSetStatus(''), 1500);
  } catch (e) {
    nbSetStatus('');
    alert('Save failed: ' + (e.message || e));
  }
}

function nbToolbarUpload() {
  const input = document.getElementById('nb-file-input');
  if (input) input.click();
}

async function nbUploadFile(file) {
  if (!file) return;
  if (!file.name.toLowerCase().endsWith('.ipynb')) {
    alert('Only .ipynb files are supported');
    return;
  }
  nbSetStatus('Uploading…');
  const fd = new FormData();
  fd.append('file', file);
  try {
    const res = await fetch('/api/notebooks/upload?overwrite=1', { method: 'POST', body: fd });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || 'Upload failed');
    }
    await loadNotebooks();
    nbSetStatus('Uploaded');
    setTimeout(() => nbSetStatus(''), 1500);
  } catch (e) {
    nbSetStatus('');
    alert('Upload failed: ' + (e.message || e));
  }
}

function nbDownload(name) {
  if (!name) return;
  window.location.href = `/api/notebooks/download?name=${encodeURIComponent(name)}`;
}

async function nbDelete(name) {
  if (!name) return;
  if (!confirm(`Delete notebook "${name}"?`)) return;
  nbSetStatus('…');
  try {
    const res = await fetch(`/api/notebooks?name=${encodeURIComponent(name)}`, { method: 'DELETE' });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || 'Delete failed');
    }
    if (nbState.lastSavedName === name) {
      nbState.lastSavedName = null;
      nbState.lastSavedAt = null;
      nbUpdateCurrentMeta();
    }
    await loadNotebooks();
    nbSetStatus('');
  } catch (e) {
    nbSetStatus('');
    alert('Delete failed: ' + (e.message || e));
  }
}

async function nbOpen(name) {
  if (!name) return;
  const hasCells = typeof window.serializeNotebookState === 'function'
    && (window.serializeNotebookState().cells || []).length > 0;
  if (hasCells && !confirm('Replace the current notebook with the selected file?')) {
    return;
  }

  nbSetStatus('Opening…');
  try {
    const res = await fetch(`/api/notebooks/raw?name=${encodeURIComponent(name)}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || 'Open failed');
    }
    const data = await res.json();
    const nb = JSON.parse(data.content);
    const state = ipynbToSporeState(nb, data.name || name);

    if (window.SPORE_WORKSPACE_STATE) {
      window.SPORE_WORKSPACE_STATE.notebook = state;
    }

    const nameEl = document.getElementById('notebook-header-name');
    if (nameEl) nameEl.value = state.name;

    if (typeof window.openNotebookPanel === 'function') {
      window.openNotebookPanel();
    } else if (typeof window.setActiveView === 'function') {
      window.setActiveView('analyze');
    }

    if (typeof window.hydrateNotebookFromWorkspace === 'function') {
      window.hydrateNotebookFromWorkspace(state);
    }

    if (typeof window.saveWorkspaceStatePatch === 'function' && typeof window.serializeNotebookState === 'function') {
      await window.saveWorkspaceStatePatch({ notebook: window.serializeNotebookState() }, true);
    }

    nbState.lastSavedName = name;
    nbState.lastSavedAt = new Date().toISOString();
    nbUpdateCurrentMeta();
    nbSetStatus('');
  } catch (e) {
    nbSetStatus('');
    alert('Open failed: ' + (e.message || e));
  }
}

function initNotebookFilesPanel() {
  const input = document.getElementById('nb-file-input');
  if (input) {
    input.addEventListener('change', () => {
      const file = input.files?.[0];
      if (file) nbUploadFile(file);
      input.value = '';
    });
  }
  nbUpdateCurrentMeta();
}

window.loadNotebooks = loadNotebooks;
window.nbSaveCurrent = nbSaveCurrent;
window.nbToolbarUpload = nbToolbarUpload;
window.nbOpen = nbOpen;
window.nbDownload = nbDownload;
window.nbDelete = nbDelete;
window.ipynbToSporeState = ipynbToSporeState;

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initNotebookFilesPanel);
} else {
  initNotebookFilesPanel();
}
