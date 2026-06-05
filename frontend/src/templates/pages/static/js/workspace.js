/**
 * Workspace view switching + persistence bootstrap (Data / Notebook / Dashboard / Export).
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
        export: 'exportPanel',
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

function openExportPanel() {
    setActiveView('export');
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
    const initialView = SPORE_WS_STATE?.active_view || 'data';
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

document.addEventListener('DOMContentLoaded', () => {
    initPreviewResize();
    bootstrapWorkspace();
});
