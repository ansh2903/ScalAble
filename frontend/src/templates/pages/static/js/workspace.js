/**
 * Workspace view switching + persistence bootstrap (Data / Notebook / Dashboard / Catalog).
 */

const SPORE_WS = window.SPORE_WORKSPACE || null;
const SPORE_WS_STATE = window.SPORE_WORKSPACE_STATE || null;

let _stateSaveTimer = null;
let _pendingStatePatch = {};
let _notebookHydrated = false;

function getActiveWorkspaceId() {
    return SPORE_WS?.id || null;
}

function getWorkspaceApiBase() {
    const id = getActiveWorkspaceId();
    if (!id) return null;
    return `/api/workspaces/${encodeURIComponent(id)}`;
}

async function saveWorkspaceStatePatch(patch, immediate = false) {
    const base = getWorkspaceApiBase();
    if (!base) return;

    _pendingStatePatch = deepMergePatch(_pendingStatePatch, patch);

    const flush = async () => {
        const body = _pendingStatePatch;
        _pendingStatePatch = {};
        try {
            await fetch(`${base}/state`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
        } catch (e) {
            console.warn('workspace state save failed', e);
        }
    };

    if (immediate) {
        clearTimeout(_stateSaveTimer);
        await flush();
        return;
    }

    clearTimeout(_stateSaveTimer);
    _stateSaveTimer = setTimeout(flush, 400);
}

function deepMergePatch(target, patch) {
    const out = { ...target };
    for (const key of Object.keys(patch)) {
        const val = patch[key];
        if (val && typeof val === 'object' && !Array.isArray(val) && key !== 'notebook' && key !== 'dashboard' && key !== 'data') {
            out[key] = { ...(out[key] || {}), ...val };
        } else if (key === 'notebook' || key === 'dashboard' || key === 'data') {
            out[key] = { ...(out[key] || {}), ...val };
        } else {
            out[key] = val;
        }
    }
    return out;
}

function setActiveView(view) {
    const panelMap = {
        data: 'dataPanel',
        analyze: 'notebookPanel',
        dashboard: 'dashboardPanel',
        catalog: 'catalogPanel',
    };

    Object.entries(panelMap).forEach(([name, id]) => {
        const panel = document.getElementById(id);
        if (!panel) return;
        const show = name === view;
        panel.classList.toggle('hidden', !show);
        if (show) {
            panel.classList.add('flex', 'flex-col', 'flex-1', 'min-h-0', 'overflow-hidden');
        }
    });

    document.querySelectorAll('.view-tab').forEach((btn) => {
        const on = btn.dataset.view === view;
        btn.classList.toggle('bg-primary', on);
        btn.classList.toggle('text-white', on);
        btn.classList.toggle('shadow-tactile', on);
        btn.classList.toggle('text-slate-500', !on);
        btn.classList.toggle('hover:text-slate-900', !on);
        btn.classList.toggle('hover:bg-white', !on);
    });

    if (view !== 'analyze' && typeof window.notebookOnLeaveView === 'function') {
        window.notebookOnLeaveView();
    }

    if (view === 'analyze' && !_notebookHydrated) {
        _notebookHydrated = true;
        if (typeof window.hydrateNotebookFromWorkspace === 'function') {
            window.hydrateNotebookFromWorkspace(SPORE_WS_STATE?.notebook);
        }
    }

    if (view === 'dashboard' && typeof window.hydrateDashboardFromWorkspace === 'function') {
        window.hydrateDashboardFromWorkspace(SPORE_WS_STATE?.dashboard);
    }

    if (view === 'catalog') {
        loadCatalog();
    }

    saveWorkspaceStatePatch({ active_view: view });
}

function openDataPanel() {
    setActiveView('data');
    
    // Smooth layout recovery hook for Monaco
    if (window.dataEditor && window.monaco) {
        // 1. Force state mapping to your dark panel theme explicitly
        window.monaco.editor.setTheme('spore-data');
        
        // 2. Tell the editor to look at its mount layout dimensions again
        // This stops it from freezing or squishing when tab containers visibility changes
        window.dataEditor.layout();
        
        // 3. Drop cursor focus back into the editor pool automatically
        window.dataEditor.focus();
    }
}

function openNotebookPanel() {
    setActiveView('analyze');
    
    // If you want your notebook cells to explicitly use the light theme, 
    // force it here, or let individual cell handlers run it:
    if (window.monaco) {
        window.monaco.editor.setTheme('spore-theme');
    }
    
    // Run layout recalculation functions for your notebook editor instances here
    if (window.notebookEditor) {
        window.notebookEditor.layout();
    }
}
function openDashboardPanel() {
    setActiveView('dashboard');
}

function openCatalogPanel() {
    setActiveView('catalog');
}

// ── Catalog (relations) ─────────────────────────────────────────────────────

let _catalogRelations = {};
let _catalogSelectedRef = null;
let _catalogActiveTab = 'schema';
let _catalogPreviewLoaded = {};
let _catalogProfileLoaded = {};

function catalogFormatBytes(n) {
    const num = Number(n) || 0;
    if (num < 1024) return `${num} B`;
    if (num < 1024 * 1024) return `${(num / 1024).toFixed(1)} KB`;
    if (num < 1024 * 1024 * 1024) return `${(num / (1024 * 1024)).toFixed(1)} MB`;
    return `${(num / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

function catalogFormatRelativeTime(iso) {
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

function catalogFormatRows(n) {
    if (n == null || n === '') return '—';
    return Number(n).toLocaleString();
}

function catalogEscapeHtml(s) {
    return String(s ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function catalogConnExists(connId) {
    if (!connId) return false;
    const select = document.getElementById('selected_db_id');
    if (!select) return false;
    return !!select.querySelector(`option[value="${CSS.escape(String(connId))}"]`);
}

function catalogCanRepull(rel) {
    const src = rel?.source;
    return !!(src?.query && src?.conn_id && catalogConnExists(src.conn_id));
}

async function loadCatalog() {
    const base = getWorkspaceApiBase();
    const listEl = document.getElementById('catalog-list');
    if (!base) {
        if (listEl) listEl.innerHTML = '<p class="text-[10px] font-mono text-slate-400 text-center py-8">No workspace</p>';
        return;
    }

    if (listEl) listEl.innerHTML = '<p class="text-[10px] font-mono text-slate-400 text-center py-8">Loading relations…</p>';

    try {
        const res = await fetch(`${base}/relations`);
        if (!res.ok) throw new Error('Failed to load relations');
        const data = await res.json();
        _catalogRelations = data.relations || {};
        renderCatalogList(Object.values(_catalogRelations));
        updateCatalogHeader(Object.values(_catalogRelations));

        if (_catalogSelectedRef && _catalogRelations[_catalogSelectedRef]) {
            selectRelation(_catalogSelectedRef, false);
        } else if (_catalogSelectedRef) {
            _catalogSelectedRef = null;
            showCatalogEmpty();
        }
    } catch (e) {
        console.warn('catalog load failed', e);
        if (listEl) listEl.innerHTML = '<p class="text-[10px] font-mono text-red-500 text-center py-8">Failed to load relations</p>';
    }
}

function updateCatalogHeader(rels) {
    const countEl = document.getElementById('catalog-count');
    const sizeEl = document.getElementById('catalog-total-size');
    const refreshEl = document.getElementById('catalog-last-refresh');

    const totalBytes = rels.reduce((sum, r) => sum + (Number(r.size_bytes) || 0), 0);
    const latest = rels.reduce((max, r) => {
        const t = r.updated_at ? new Date(r.updated_at).getTime() : 0;
        return t > max ? t : max;
    }, 0);

    if (countEl) countEl.textContent = String(rels.length);
    if (sizeEl) sizeEl.textContent = catalogFormatBytes(totalBytes);
    if (refreshEl) {
        refreshEl.textContent = latest ? catalogFormatRelativeTime(new Date(latest).toISOString()) : '—';
    }
}

function getCatalogSearchQuery() {
    return (document.getElementById('catalog-search')?.value || '').trim().toLowerCase();
}

function renderCatalogList(rels) {
    const listEl = document.getElementById('catalog-list');
    if (!listEl) return;

    const q = getCatalogSearchQuery();
    const filtered = rels
        .filter((r) => {
            if (!q) return true;
            const label = (r.label || r.name || r.ref || '').toLowerCase();
            return label.includes(q);
        })
        .sort((a, b) => (a.label || a.name || '').localeCompare(b.label || b.name || ''));

    if (!filtered.length) {
        listEl.innerHTML = '<p class="text-[10px] font-mono text-slate-400 text-center py-8">No materialized relations yet</p>';
        return;
    }

    listEl.innerHTML = filtered.map((rel) => {
        const ref = rel.ref || rel.name;
        const selected = ref === _catalogSelectedRef;
        const meta = [
            catalogFormatRows(rel.row_count) + ' rows',
            catalogFormatBytes(rel.size_bytes),
            catalogFormatRelativeTime(rel.updated_at),
        ].join(' · ');
        return `
            <button type="button" data-catalog-ref="${catalogEscapeHtml(ref)}"
                class="catalog-list-item w-full flex items-center gap-3 rounded-xl border p-3 text-left transition-colors
                ${selected ? 'border-primary/40 bg-primary-soft/30' : 'border-slate-200 hover:border-primary/30 bg-white'}">
                <div class="w-9 h-9 rounded-pill bg-primary-soft border border-primary/20 flex items-center justify-center shrink-0">
                    <span class="material-symbols-outlined text-primary text-[18px]">database</span>
                </div>
                <div class="flex-1 min-w-0">
                    <p class="text-[11px] font-black text-slate-900 font-mono truncate">${catalogEscapeHtml(rel.label || ref)}</p>
                    <p class="text-[9px] font-mono text-slate-400 mt-0.5">${catalogEscapeHtml(meta)}</p>
                </div>
                <span class="text-[9px] font-mono uppercase text-slate-400 shrink-0">${catalogEscapeHtml(rel.format || '')}</span>
            </button>`;
    }).join('');

    listEl.querySelectorAll('.catalog-list-item').forEach((btn) => {
        btn.addEventListener('click', () => {
            const ref = btn.dataset.catalogRef;
            if (ref) selectRelation(ref);
        });
    });
}

function showCatalogEmpty() {
    document.getElementById('catalog-detail-empty')?.classList.remove('hidden');
    document.getElementById('catalog-detail')?.classList.add('hidden');
}

function showCatalogDetail() {
    document.getElementById('catalog-detail-empty')?.classList.add('hidden');
    document.getElementById('catalog-detail')?.classList.remove('hidden');
}

function setCatalogDetailTab(tab) {
    _catalogActiveTab = tab;
    document.querySelectorAll('.catalog-detail-tab').forEach((btn) => {
        const on = btn.dataset.catalogTab === tab;
        btn.classList.toggle('bg-primary', on);
        btn.classList.toggle('text-white', on);
        btn.classList.toggle('shadow-tactile', on);
        btn.classList.toggle('text-slate-500', !on);
        btn.classList.toggle('hover:bg-white', !on);
    });
    document.querySelectorAll('.catalog-tab-pane').forEach((pane) => {
        const id = pane.id?.replace('catalog-tab-', '');
        pane.classList.toggle('hidden', id !== tab);
    });

    if (tab === 'preview' && _catalogSelectedRef && !_catalogPreviewLoaded[_catalogSelectedRef]) {
        loadCatalogPreview(_catalogSelectedRef);
    }
    if (tab === 'profile' && _catalogSelectedRef && !_catalogProfileLoaded[_catalogSelectedRef]) {
        loadCatalogProfile(_catalogSelectedRef);
    }
}

function renderCatalogSchema(rel) {
    const body = document.getElementById('catalog-schema-body');
    if (!body) return;
    const schema = rel.schema || [];
    if (!schema.length) {
        body.innerHTML = '<tr><td colspan="2" class="px-3 py-4 text-slate-400 text-center">No schema available</td></tr>';
        return;
    }
    body.innerHTML = schema.map((col) => `
        <tr class="border-b border-slate-50 last:border-0">
            <td class="px-3 py-2 font-mono text-slate-800">${catalogEscapeHtml(col.name)}</td>
            <td class="px-3 py-2 font-mono text-slate-500">${catalogEscapeHtml(col.type)}</td>
        </tr>`).join('');
}

function selectRelation(ref, rerenderList = true) {
    const rel = _catalogRelations[ref];
    if (!rel) return;

    _catalogSelectedRef = ref;
    _catalogPreviewLoaded[ref] = false;
    _catalogProfileLoaded[ref] = false;

    if (rerenderList) {
        renderCatalogList(Object.values(_catalogRelations));
    }

    showCatalogDetail();

    const nameEl = document.getElementById('catalog-detail-name');
    const metaEl = document.getElementById('catalog-detail-meta');
    if (nameEl) nameEl.textContent = rel.label || ref;
    if (metaEl) {
        metaEl.textContent = [
            catalogFormatRows(rel.row_count) + ' rows',
            catalogFormatBytes(rel.size_bytes),
            (rel.format || '').toUpperCase(),
            'updated ' + catalogFormatRelativeTime(rel.updated_at),
        ].join(' · ');
    }

    const repullBtn = document.getElementById('catalog-btn-repull');
    if (repullBtn) {
        repullBtn.disabled = !catalogCanRepull(rel);
        repullBtn.title = catalogCanRepull(rel)
            ? 'Re-run source query and refresh materialized data'
            : 'Re-pull requires a stored source query and active connection';
    }

    renderCatalogSchema(rel);
    setCatalogDetailTab('schema');

    document.getElementById('catalog-preview-wrap')?.classList.add('hidden');
    document.getElementById('catalog-preview-loading')?.classList.remove('hidden');
    document.getElementById('catalog-profile-wrap')?.classList.add('hidden');
    document.getElementById('catalog-profile-loading')?.classList.remove('hidden');
}

async function loadCatalogPreview(ref) {
    const base = getWorkspaceApiBase();
    const loading = document.getElementById('catalog-preview-loading');
    const wrap = document.getElementById('catalog-preview-wrap');
    const head = document.getElementById('catalog-preview-head');
    const body = document.getElementById('catalog-preview-body');
    if (!base || !head || !body) return;

    loading?.classList.remove('hidden');
    wrap?.classList.add('hidden');

    try {
        const res = await fetch(`${base}/relations/${encodeURIComponent(ref)}/preview?limit=100`);
        if (!res.ok) throw new Error('Preview failed');
        const data = await res.json();
        const cols = data.columns || [];
        const rows = data.rows || [];

        head.innerHTML = `<tr>${cols.map((c) => `<th class="px-2 py-1.5 font-black text-[9px] uppercase text-slate-400 whitespace-nowrap">${catalogEscapeHtml(c)}</th>`).join('')}</tr>`;
        body.innerHTML = rows.map((row) => {
            const cells = cols.map((c) => {
                const v = row[c];
                const text = v == null ? '' : (typeof v === 'object' ? JSON.stringify(v) : String(v));
                return `<td class="px-2 py-1 border-t border-slate-50 text-slate-700 whitespace-nowrap max-w-[200px] truncate" title="${catalogEscapeHtml(text)}">${catalogEscapeHtml(text)}</td>`;
            }).join('');
            return `<tr>${cells}</tr>`;
        }).join('') || '<tr><td class="px-2 py-4 text-slate-400" colspan="' + cols.length + '">No rows</td></tr>';

        _catalogPreviewLoaded[ref] = true;
        loading?.classList.add('hidden');
        wrap?.classList.remove('hidden');
    } catch (e) {
        console.warn('catalog preview failed', e);
        if (loading) loading.textContent = 'Failed to load preview';
    }
}

async function loadCatalogProfile(ref) {
    const base = getWorkspaceApiBase();
    const loading = document.getElementById('catalog-profile-loading');
    const wrap = document.getElementById('catalog-profile-wrap');
    const head = document.getElementById('catalog-profile-head');
    const body = document.getElementById('catalog-profile-body');
    if (!base || !head || !body) return;

    loading?.classList.remove('hidden');
    wrap?.classList.add('hidden');

    try {
        const res = await fetch(`${base}/relations/${encodeURIComponent(ref)}/profile`);
        if (!res.ok) throw new Error('Profile failed');
        const data = await res.json();
        const columns = data.columns || [];
        if (!columns.length) {
            if (loading) loading.textContent = 'No profile data';
            return;
        }

        const keys = Object.keys(columns[0]);
        head.innerHTML = `<tr>${keys.map((k) => `<th class="px-2 py-1.5 font-black text-[9px] uppercase text-slate-400 whitespace-nowrap">${catalogEscapeHtml(k)}</th>`).join('')}</tr>`;
        body.innerHTML = columns.map((row) => {
            const cells = keys.map((k) => {
                const v = row[k];
                const text = v == null ? '' : String(v);
                return `<td class="px-2 py-1 border-t border-slate-50 text-slate-700 whitespace-nowrap">${catalogEscapeHtml(text)}</td>`;
            }).join('');
            return `<tr>${cells}</tr>`;
        }).join('');

        _catalogProfileLoaded[ref] = true;
        loading?.classList.add('hidden');
        wrap?.classList.remove('hidden');
    } catch (e) {
        console.warn('catalog profile failed', e);
        if (loading) loading.textContent = 'Failed to load profile';
    }
}

function downloadRelation(ref, fmt) {
    const base = getWorkspaceApiBase();
    if (!base || !ref) return;
    const url = `${base}/relations/${encodeURIComponent(ref)}/download?format=${encodeURIComponent(fmt)}`;
    window.location.href = url;
}

async function repullRelation(ref) {
    const rel = _catalogRelations[ref];
    if (!rel || !catalogCanRepull(rel)) return;

    const src = rel.source;
    const repullBtn = document.getElementById('catalog-btn-repull');
    if (repullBtn) {
        repullBtn.disabled = true;
        repullBtn.textContent = 'Pulling…';
    }

    try {
        const formData = new FormData();
        formData.append('query', src.query);
        formData.append('id', src.conn_id);
        formData.append('stream_name', ref);
        formData.append('format', rel.format || 'parquet');

        const response = await fetch('/ingest', { method: 'POST', body: formData });
        if (!response.ok) throw new Error('Ingest failed');

        const reader = response.body?.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let hadError = false;

        if (reader) {
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';
                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    try {
                        const chunk = JSON.parse(line.slice(6));
                        if (chunk.type === 'error') hadError = true;
                    } catch (_) { /* ignore */ }
                }
            }
        }

        if (hadError) throw new Error('Re-pull failed');

        if (typeof window.registerRelationAfterIngest === 'function') {
            await window.registerRelationAfterIngest(ref, src.conn_id, src.query);
        }

        await loadCatalog();
        selectRelation(ref);
    } catch (e) {
        console.warn('catalog repull failed', e);
        alert('Re-pull failed: ' + (e.message || e));
    } finally {
        if (repullBtn) {
            repullBtn.disabled = !catalogCanRepull(_catalogRelations[ref]);
            repullBtn.innerHTML = '<span class="material-symbols-outlined text-[14px]">sync</span> Re-pull';
        }
    }
}

async function dropRelation(ref) {
    const rel = _catalogRelations[ref];
    const label = rel?.label || ref;
    if (!confirm(`Drop relation "${label}"? This removes the materialized data from the workspace volume.`)) {
        return;
    }

    const base = getWorkspaceApiBase();
    if (!base) return;

    try {
        const res = await fetch(`${base}/relations/${encodeURIComponent(ref)}`, { method: 'DELETE' });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.error || 'Delete failed');
        }
        _catalogSelectedRef = null;
        delete _catalogPreviewLoaded[ref];
        delete _catalogProfileLoaded[ref];
        showCatalogEmpty();
        await loadCatalog();
    } catch (e) {
        console.warn('catalog drop failed', e);
        alert('Drop failed: ' + (e.message || e));
    }
}

function toggleCatalogDownloadDropdown(show) {
    const dropdown = document.getElementById('catalog-download-dropdown');
    if (!dropdown) return;
    if (show === false) {
        dropdown.classList.add('hidden');
    } else {
        dropdown.classList.toggle('hidden');
    }
}

function initCatalogPanel() {
    document.getElementById('catalog-search')?.addEventListener('input', () => {
        renderCatalogList(Object.values(_catalogRelations));
    });

    document.querySelectorAll('.catalog-detail-tab').forEach((btn) => {
        btn.addEventListener('click', () => {
            const tab = btn.dataset.catalogTab;
            if (tab) setCatalogDetailTab(tab);
        });
    });

    document.getElementById('catalog-download-toggle')?.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleCatalogDownloadDropdown();
    });

    document.querySelectorAll('.catalog-download-opt').forEach((btn) => {
        btn.addEventListener('click', () => {
            const fmt = btn.dataset.catalogFmt;
            toggleCatalogDownloadDropdown(false);
            if (_catalogSelectedRef && fmt) downloadRelation(_catalogSelectedRef, fmt);
        });
    });

    document.getElementById('catalog-btn-repull')?.addEventListener('click', () => {
        if (_catalogSelectedRef) repullRelation(_catalogSelectedRef);
    });

    document.getElementById('catalog-btn-drop')?.addEventListener('click', () => {
        if (_catalogSelectedRef) dropRelation(_catalogSelectedRef);
    });

    document.addEventListener('click', (e) => {
        if (!e.target.closest('#catalog-download-menu')) {
            toggleCatalogDownloadDropdown(false);
        }
    });
}

function resolveDataKind(connOrKind) {
    const kindAliasMap = {
        database: 'database',
        databases: 'database',
        db: 'database',
        warehouse: 'warehouse',
        warehouses: 'warehouse',
        'data warehouse': 'warehouse',
        'data warehouses': 'warehouse',
        api: 'api',
        apis: 'api',
        file: 'file',
        files: 'file',
        'local file': 'file',
        'local files': 'file',
        postgresql: 'database',
        mongodb: 'database',
        mysql: 'database',
        mssql: 'database',
        bigquery: 'warehouse',
        snowflake: 'warehouse',
        redshift: 'warehouse',
        rest_api: 'api',
        graphql_api: 'api',
        csv_file: 'file',
        excel_file: 'file',
        json_file: 'file',
        parquet_file: 'file',
    };

    const rawKind = typeof connOrKind === 'string'
        ? connOrKind
        : (connOrKind?.kind || connOrKind?.metadata?.kind || connOrKind?.source_type || connOrKind?.db_type || '');
    const normalized = String(rawKind).trim().toLowerCase();

    if (kindAliasMap[normalized]) return kindAliasMap[normalized];

    const sourceType = typeof connOrKind === 'string'
        ? ''
        : String(connOrKind?.source_type || connOrKind?.db_type || '').trim().toLowerCase();
    return kindAliasMap[sourceType] || 'database';
}

function setDataKind(connOrKind) {
    const kind = resolveDataKind(connOrKind);
    const map = {
        database: 'sql-data',
        warehouse: 'sql-data',
        api: 'api-data',
        file: 'files-data',
    };
    const showId = map[kind] || 'sql-data';

    ['sql-data', 'api-data', 'files-data'].forEach((id) => {
        const el = document.getElementById(id);
        if (!el) return;
        const show = id === showId;
        el.classList.toggle('hidden', !show);
        el.style.display = show ? 'flex' : 'none';
    });
}

function updateDataHeader(conn) {
    const nameEl = document.getElementById('data-header-name');
    const extEl = document.getElementById('data-header-ext');
    const vendorEl = document.getElementById('data-header-vendor');
    const contextEl = document.getElementById('data-header-context');
    const modeEl = document.getElementById('data-header-mode');

    if (!nameEl || !vendorEl || !contextEl || !modeEl) return;

    const wsName = SPORE_WS?.name || 'Workspace';
    const label = conn?.display_name || conn?.name || wsName;
    const kind = resolveDataKind(conn);
    const sourceType = (conn?.source_type || conn?.db_type || '').toString();

    nameEl.textContent = label;
    if (extEl) {
        extEl.textContent = kind === 'api' ? '.api' : kind === 'file' ? '.file' : '.db';
    }

    vendorEl.textContent = sourceType || '—';

    const meta = conn?.metadata || {};
    if (kind === 'database') contextEl.textContent = meta.schema || 'public';
    else if (kind === 'warehouse') contextEl.textContent = meta.dataset || meta.schema || 'default';
    else if (kind === 'api') contextEl.textContent = 'Requests';
    else if (kind === 'file') contextEl.textContent = 'Preview';
    else contextEl.textContent = '—';

    modeEl.textContent = kind === 'api' ? 'Request' : kind === 'file' ? 'Preview' : 'Query';
}

function setDataTab(tab) {
    ['query', 'preview', 'filters'].forEach((name) => {
        const pane = document.getElementById('data-tab-' + name);
        if (pane) pane.classList.toggle('hidden', name !== tab);
    });

    const queryActions = document.getElementById('data-tab-query-actions');
    if (queryActions) queryActions.classList.toggle('hidden', tab !== 'query');

    document.querySelectorAll('.data-work-tab').forEach((btn) => {
        const on = btn.dataset.tab === tab;
        btn.classList.toggle('bg-primary', on);
        btn.classList.toggle('text-white', on);
        btn.classList.toggle('shadow-tactile', on);
        btn.classList.toggle('text-slate-500', !on);
        btn.classList.toggle('hover:text-slate-900', !on);
        btn.classList.toggle('hover:bg-white', !on);
    });
}

function initPreviewResize() {
    const handle = document.getElementById('preview-resize-handle');
    const preview = document.getElementById('data-tab-preview');
    if (!handle || !preview) return;

    const container = preview.parentElement;
    if (!container) return;

    let dragging = false;

    const onMove = (clientY) => {
        const rect = container.getBoundingClientRect();
        const relative = clientY - rect.top;
        const minTop = 80;
        const maxTop = rect.height - 80;
        const clamped = Math.max(minTop, Math.min(maxTop, relative));
        const pct = (clamped / rect.height) * 100;
        preview.style.top = `${pct}%`;
    };

    handle.addEventListener('mousedown', (e) => {
        dragging = true;
        e.preventDefault();
        document.body.style.userSelect = 'none';
    });

    document.addEventListener('mousemove', (e) => {
        if (!dragging) return;
        onMove(e.clientY);
    });

    document.addEventListener('mouseup', () => {
        if (!dragging) return;
        dragging = false;
        document.body.style.userSelect = '';
    });

    handle.addEventListener('touchstart', () => {
        dragging = true;
    }, { passive: true });

    document.addEventListener('touchmove', (e) => {
        if (!dragging || !e.touches[0]) return;
        onMove(e.touches[0].clientY);
    }, { passive: true });

    document.addEventListener('touchend', () => {
        dragging = false;
    });
}

function bindConnectionPersistence() {
    const select = document.getElementById('selected_db_id');
    if (!select) return;

    if (SPORE_WS_STATE?.selected_connection_id) {
        const opt = select.querySelector(`option[value="${SPORE_WS_STATE.selected_connection_id}"]`);
        if (opt) select.value = SPORE_WS_STATE.selected_connection_id;
    }

    select.addEventListener('change', () => {
        const val = select.value || null;
        saveWorkspaceStatePatch({ selected_connection_id: val });
    });
}

function applyDashboardShell(dashboard) {
    if (!dashboard || typeof dashboard !== 'object') return;
    const titleEl = document.getElementById('dashboard-header-name');
    if (titleEl && dashboard.title) {
        titleEl.textContent = dashboard.title;
    }
    const widgetCount = document.getElementById('dashboard-widget-count');
    if (widgetCount) {
        let count = 0;
        if (Array.isArray(dashboard.pages)) {
            const active = dashboard.pages.find((p) => p.id === dashboard.activePageId) || dashboard.pages[0];
            count = (active?.widgets || []).length;
        } else if (Array.isArray(dashboard.widgets)) {
            count = dashboard.widgets.length;
        }
        widgetCount.textContent = String(count);
    }
    if (typeof window.hydrateDashboardFromWorkspace === 'function') {
        window.hydrateDashboardFromWorkspace(dashboard);
    }
}

function bootstrapWorkspace() {
    const saved = SPORE_WS_STATE?.active_view || 'data';
    const initialView = saved === 'export' ? 'catalog' : saved;
    setActiveView(initialView);
    bindConnectionPersistence();

    if (SPORE_WS_STATE?.dashboard) {
        applyDashboardShell(SPORE_WS_STATE.dashboard);
    }

    if (typeof window.hydrateDataHistoryFromWorkspace === 'function') {
        window.hydrateDataHistoryFromWorkspace();
    }
}

window.getActiveWorkspaceId = getActiveWorkspaceId;
window.getWorkspaceApiBase = getWorkspaceApiBase;
window.saveWorkspaceStatePatch = saveWorkspaceStatePatch;
window.setActiveView = setActiveView;
window.getWorkspaceDashboardState = () => SPORE_WS_STATE?.dashboard || { widgets: [], layout: { columns: 12 }, metadata: {} };
window.setDataKind = setDataKind;
window.updateDataHeader = updateDataHeader;
window.resolveDataKind = resolveDataKind;
window.loadCatalog = loadCatalog;
window.openCatalogPanel = openCatalogPanel;
window.openDataPanel = openDataPanel;
window.openNotebookPanel = openNotebookPanel;
window.openDashboardPanel = openDashboardPanel;

document.addEventListener('DOMContentLoaded', () => {
    initPreviewResize();
    initCatalogPanel();
    bootstrapWorkspace();
});
