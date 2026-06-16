// ─── Sidebar ────────────────────────────────────────────────
let activeSidePanel = null;

function _getConnections() {
    return Array.isArray(window.SPORE_CONNECTIONS) ? window.SPORE_CONNECTIONS : [];
}

function openSidePanel(name) {
    const panel = document.getElementById('side-panel');

    // Toggle — clicking same tab closes it
    if (activeSidePanel === name) {
        closeSidePanel();
        return;
    }

    // Swap visible panel
    document.querySelectorAll('.side-panel-content').forEach(p => {
        p.classList.add('hidden');
        p.style.display = '';
    });
    document.querySelectorAll('.sidebar-tab').forEach(t => t.classList.remove('active'));

    const target = document.getElementById(`panel-${name}`);
    const tab = document.getElementById(`tab-${name}`);
    if (target) { target.classList.remove('hidden'); target.style.display = 'flex'; }
    if (tab) tab.classList.add('active');

    // Slide in — translate instead of width, no layout shift
    panel.style.width = '220px';
    activeSidePanel = name;

    if (name === 'files') loadFs();
    if (name === 'notebook' && typeof window.loadNotebooks === 'function') loadNotebooks();
}

function closeSidePanel() {
    const panel = document.getElementById('side-panel');
    panel.style.width = '0px';
    document.querySelectorAll('.sidebar-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.side-panel-content').forEach(p => {
        p.classList.add('hidden');
        p.style.display = '';
    });
    activeSidePanel = null;
}

// Global variable to store current metadata
let currentMetadata = null;

function _setChatConnChip(conn) {
    const chip = document.getElementById('chat-conn-chip');
    if (!chip) return;
    const label = conn?.display_name || conn?.name || 'Select Context';
    chip.childNodes[0].textContent = `${label} `;
}

function onActiveConnectionChange(connId) {
    const conns = _getConnections();
    const conn = conns.find(c => String(c.id) === String(connId));
    if (!conn) return;

    // Workspace-level updates (defined in workspace.js)
    if (typeof window.setDataKind === 'function') window.setDataKind(conn);
    if (typeof window.updateDataHeader === 'function') window.updateDataHeader(conn);

    const kind = typeof window.resolveDataKind === 'function'
        ? window.resolveDataKind(conn)
        : (conn.kind || '');
    if (kind === 'file' && typeof window.runFilePreview === 'function') {
        window.runFilePreview(conn);
    } else if (kind === 'api' && typeof window.initApiPanel === 'function') {
        window.initApiPanel(conn);
    }

    _setChatConnChip(conn);
    updateSchemaPanel(connId);
}

// Auto-open side panel and preselect first connection
document.addEventListener('DOMContentLoaded', () => {
    const conns = _getConnections();
    const select = document.getElementById('selected_db_id');
    if (!select) return;

    if (!conns.length) {
        _setChatConnChip(null);
        return;
    }

    // Open the source browser by default.
    openSidePanel('database');

    // If nothing selected, select the first connection.
    if (!select.value) {
        select.value = String(conns[0].id);
    }

    // Always route the current value so preselected/persisted values hydrate too.
    select.dispatchEvent(new Event('change', { bubbles: true }));
});

// Listen for dropdown changes
document.getElementById('selected_db_id')?.addEventListener('change', function(e) {
    onActiveConnectionChange(e.target.value);
});

async function updateSchemaPanel(dbId) {
    if (!dbId) return;

    // Show loading state in the tree
    const treeContainer = document.getElementById('schema-tree');
    treeContainer.innerHTML = `<div class="animate-pulse flex flex-col gap-2 p-4">
        <div class="h-2 bg-slate-100 rounded w-3/4"></div>
        <div class="h-2 bg-slate-100 rounded w-1/2"></div>
    </div>`;

    try {
        // Fetch fresh metadata from your Flask backend
        const response = await fetch(`/api/metadata/${encodeURIComponent(dbId)}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        const actualMetadata = Array.isArray(data.metadata) ? data.metadata[1] : data.metadata;
        const conns = _getConnections();
        const idx = conns.findIndex(c => String(c.id) === String(dbId));
        if (idx >= 0 && actualMetadata) {
            conns[idx].metadata = actualMetadata;
            window.SPORE_CONNECTIONS = conns;
        }
        renderMetadata(actualMetadata);
    } catch (err) {
        treeContainer.innerHTML = `<div class="text-[9px] text-red-400 text-center py-8 font-bold">Failed to load metadata</div>`;
    }
}

function renderMetadata(meta) {
    const treeContainer = document.getElementById('schema-tree');
    const dbNameLabel = document.getElementById('db-name-label');
    const tableCount = document.getElementById('table-count');
    const schemaName = document.getElementById('schema-name');

    const kind = meta?.kind || (meta?.tables ? 'database' : null);

    // Update Header Stats (kind-aware)
    if (kind === 'file') {
        dbNameLabel.innerText = 'Files';
        const entities = meta?.entities || {};
        tableCount.innerText = Object.keys(entities).length;
        schemaName.innerText = '—';
    } else if (kind === 'api') {
        dbNameLabel.innerText = 'API';
        const entities = meta?.entities || {};
        tableCount.innerText = Object.keys(entities).length;
        schemaName.innerText = '—';
    } else {
        dbNameLabel.innerText = meta.database || meta.project || 'Source';
        tableCount.innerText = meta.table_count || Object.keys(meta.tables || {}).length || 0;
        schemaName.innerText = meta.schema || meta.dataset || 'public';
    }

    let html = '';

    if (kind === 'api') {
        const baseUrl = meta?.base_url || meta?.endpoint || '';
        html += `
            <div class="px-2 py-2">
                <div class="rounded-lg border border-slate-100 bg-slate-50/60 p-2">
                    <div class="text-[8px] font-black uppercase tracking-widest text-slate-400 mb-1">Base URL</div>
                    <div class="text-[10px] font-mono text-slate-700 break-all">${baseUrl || '—'}</div>
                </div>
            </div>
            <div class="text-[9px] text-slate-400 text-center py-10 font-bold italic">
                Saved requests will appear here
            </div>
        `;
        treeContainer.innerHTML = html;
        return;
    }

    if (kind === 'file') {
        const entities = meta?.entities || {};
        Object.entries(entities).forEach(([name, details]) => {
            const cols = Array.isArray(details?.columns) ? details.columns : [];
            const types = details?.column_types || {};
            html += `
                <div class="group border border-transparent hover:border-slate-100 rounded-lg transition-all">
                    <button onclick="this.nextElementSibling.classList.toggle('hidden')" 
                        class="w-full flex items-center gap-2 px-2 py-1.5 hover:bg-slate-50 rounded-md transition-all text-left">
                        <span class="material-symbols-outlined text-[14px] text-slate-400 group-hover:text-primary">description</span>
                        <div class="flex flex-col min-w-0">
                            <span class="text-[10px] font-black text-slate-700 leading-none truncate">${name}</span>
                            <span class="text-[8px] text-slate-400 font-bold uppercase tracking-tighter">${details?.size_pretty || ''}</span>
                        </div>
                        <span class="material-symbols-outlined ml-auto text-[12px] text-slate-300">expand_more</span>
                    </button>
                    <div class="hidden pl-7 pr-2 pb-2 space-y-1 mt-1 border-l-2 border-slate-100 ml-3">
                        ${cols.map((col) => `
                            <div class="flex items-center justify-between group/row">
                                <span class="text-[9px] font-bold text-slate-500">${col}</span>
                                <span class="text-[8px] font-mono text-slate-300 group-hover/row:text-primary transition-colors">${types[col] || ''}</span>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
        });

        treeContainer.innerHTML = html || `<div class="text-[9px] text-slate-400 text-center py-8 font-bold">No file metadata</div>`;
        return;
    }

    // Default: DB/Warehouse table tree
    Object.entries(meta.tables || {}).forEach(([tableName, details]) => {
        html += `
            <div class="group border border-transparent hover:border-slate-100 rounded-lg transition-all">
                <button onclick="this.nextElementSibling.classList.toggle('hidden')" 
                    class="w-full flex items-center gap-2 px-2 py-1.5 hover:bg-slate-50 rounded-md transition-all text-left">
                    <span class="material-symbols-outlined text-[14px] text-slate-400 group-hover:text-primary">table_chart</span>
                    <div class="flex flex-col">
                        <span class="text-[10px] font-black text-slate-700 leading-none">${tableName}</span>
                        <span class="text-[8px] text-slate-400 font-bold uppercase tracking-tighter">${details.row_count} rows • ${details.size_pretty}</span>
                    </div>
                    <span class="material-symbols-outlined ml-auto text-[12px] text-slate-300">expand_more</span>
                </button>
                <div class="hidden pl-7 pr-2 pb-2 space-y-1 mt-1 border-l-2 border-slate-100 ml-3">
                    ${(details.columns || []).map((col) => `
                        <div class="flex items-center justify-between group/row">
                            <span class="text-[9px] font-bold text-slate-500">${col}</span>
                            <span class="text-[8px] font-mono text-slate-300 group-hover/row:text-primary transition-colors">${(details.column_types || {})[col] || ''}</span>
                        </div>
                    `).join('')}
                </div>
            </div>`;
    });

    treeContainer.innerHTML = html || `<div class="text-[9px] text-slate-400 text-center py-8 font-bold">Schema is empty</div>`;
}

// Logic for the refresh button
async function refreshSchema() {
    const dbId = document.getElementById('selected_db_id').value;
    if (dbId) await updateSchemaPanel(dbId);
}

// ─── File Manager (volumes/streams) ───────────────────────────
const fsState = {
    expanded: new Set(['']),
    selected: null,
    cache: new Map(),
    totalPretty: '0 B',
    inlineEdit: null,
};

window.loadStreams = () => loadFs();

function fsSetStatus(msg) {
    const el = document.getElementById('fs-status');
    if (el) el.textContent = msg || '';
}

function fsJoinPath(parent, name) {
    const p = (parent || '').replace(/\/+$/, '');
    return p ? `${p}/${name}` : name;
}

function fsParentPath(path) {
    const i = path.lastIndexOf('/');
    return i === -1 ? '' : path.slice(0, i);
}

function fsBasename(path) {
    const i = path.lastIndexOf('/');
    return i === -1 ? path : path.slice(i + 1);
}

function fmtSize(b) {
    if (b < 1024) return `${b} B`;
    if (b < 1024 ** 2) return `${(b / 1024).toFixed(1)} KB`;
    if (b < 1024 ** 3) return `${(b / 1024 ** 2).toFixed(1)} MB`;
    return `${(b / 1024 ** 3).toFixed(2)} GB`;
}

function fsFileIcon(name) {
    if (name === 'working.parquet') return { icon: 'terminal', cls: 'text-indigo-400' };
    const ext = (name.split('.').pop() || '').toLowerCase();
    if (['parquet', 'csv', 'tsv', 'json', 'xlsx', 'xls'].includes(ext)) {
        return { icon: 'database', cls: 'text-slate-300' };
    }
    return { icon: 'description', cls: 'text-slate-300' };
}

function fsEscapeHtml(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

async function fsFetchList(dirPath) {
    const q = dirPath ? `?path=${encodeURIComponent(dirPath)}` : '';
    const res = await fetch(`/api/fs/list${q}`);
    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || 'Failed to list');
    }
    const data = await res.json();
    fsState.cache.set(dirPath, data.entries);
    if (dirPath === '') {
        fsState.totalPretty = data.total_pretty || fmtSize(data.total_bytes || 0);
        const storage = document.getElementById('storage-used');
        if (storage) storage.textContent = fsState.totalPretty;
    }
    return data;
}

async function loadFs() {
    const tree = document.getElementById('fs-tree');
    if (!tree) return;
    fsSetStatus('Loading…');
    try {
        await fsFetchList('');
        for (const dir of [...fsState.expanded]) {
            if (dir) await fsFetchList(dir).catch(() => fsState.expanded.delete(dir));
        }
        renderTree();
        fsSetStatus('');
    } catch (e) {
        tree.innerHTML = `<div class="text-[9px] text-red-400 text-center py-6 font-bold">${fsEscapeHtml(e.message)}</div>`;
        fsSetStatus('');
    }
}

function renderTree() {
    const tree = document.getElementById('fs-tree');
    if (!tree) return;
    const rootEntries = fsState.cache.get('') || [];
    if (!rootEntries.length && !fsState.inlineEdit) {
        tree.innerHTML = `
            <div class="flex flex-col items-center justify-center py-12 opacity-40">
                <span class="material-symbols-outlined text-[32px] mb-2">folder_off</span>
                <span class="text-[10px] font-medium">Empty workspace</span>
            </div>`;
        return;
    }
    tree.innerHTML = renderDirChildren('', 0);
    bindFsTreeEvents();
}

function renderDirChildren(dirPath, depth) {
    const entries = fsState.cache.get(dirPath) || [];
    let html = '';
    if (fsState.inlineEdit && fsState.inlineEdit.parent === dirPath) {
        html += renderInlineInputRow(dirPath, depth, fsState.inlineEdit);
    }
    for (const entry of entries) {
        html += renderEntryRow(entry, depth);
        if (entry.type === 'dir' && fsState.expanded.has(entry.path)) {
            html += `<div class="fs-children" data-parent="${fsEscapeHtml(entry.path)}">`;
            html += renderDirChildren(entry.path, depth + 1);
            html += '</div>';
        }
    }
    return html;
}

function renderEntryRow(entry, depth) {
    const isDir = entry.type === 'dir';
    const expanded = isDir && fsState.expanded.has(entry.path);
    const selected = fsState.selected === entry.path ? ' is-selected' : '';
    const pad = 4 + depth * 4;
    const { icon, cls } = isDir
        ? { icon: expanded ? 'folder_open' : 'folder', cls: 'text-slate-400' }
        : fsFileIcon(entry.name);
    const chevron = isDir
        ? `<span class="material-symbols-outlined fs-chevron text-[16px] text-slate-400 ${expanded ? 'expanded' : ''}">chevron_right</span>`
        : `<span class="fs-chevron"></span>`;
    const badge = entry.is_stream
        ? '<span class="fs-badge-stream">STREAM</span>'
        : '';
    const warn = entry.memory_safe === false
        ? '<span class="material-symbols-outlined text-[14px] text-slate-400" title="Large file">warning</span>'
        : '';
    const size = entry.size_pretty ? `<span class="fs-size">${fsEscapeHtml(entry.size_pretty)}</span>` : '';

    return `
        <div class="fs-row${selected}"
             data-path="${fsEscapeHtml(entry.path)}"
             data-type="${entry.type}"
             data-name="${fsEscapeHtml(entry.name)}"
             style="padding-left:${pad}px"
             draggable="true">
            ${chevron}
            <span class="material-symbols-outlined text-[14px] ${cls}">${icon}</span>
            <span class="fs-name" title="${fsEscapeHtml(entry.path)}">${fsEscapeHtml(entry.name)}</span>
            ${badge}
            ${warn}
            ${size}
            <button type="button" class="fs-more-btn" data-fs-more="1" title="More actions" aria-label="More actions" draggable="false">
                <span class="material-symbols-outlined text-[14px]">more_vert</span>
            </button>
        </div>`;
}

function renderInlineInputRow(parentPath, depth, edit) {
    const pad = 8 + depth * 12;
    const value = edit.defaultName || '';
    return `
        <div class="fs-row is-selected fs-inline-row" style="padding-left:${pad}px" data-inline="1">
            <span class="fs-chevron"></span>
            <span class="material-symbols-outlined text-[14px] text-slate-300">${edit.kind === 'dir' ? 'folder' : 'description'}</span>
            <input type="text" class="fs-inline-input flex-1 text-[10px] font-bold border border-primary/30 rounded px-1 py-0.5 min-w-0"
                   value="${fsEscapeHtml(value)}" placeholder="${edit.kind === 'dir' ? 'folder name' : 'file name'}">
        </div>`;
}

function bindFsTreeEvents() {
    const tree = document.getElementById('fs-tree');
    if (!tree || tree.dataset.fsBound === '1') return;
    tree.dataset.fsBound = '1';

    tree.addEventListener('click', onFsTreeClick);
    tree.addEventListener('dblclick', onFsTreeDblClick);
    tree.addEventListener('contextmenu', onFsTreeContextMenu);
    tree.addEventListener('dragstart', onFsDragStart);
    tree.addEventListener('dragend', onFsDragEnd);
    tree.addEventListener('dragover', onFsDragOver);
    tree.addEventListener('dragleave', onFsDragLeave);
    tree.addEventListener('drop', onFsDrop);

    const fileInput = document.getElementById('fs-file-input');
    if (fileInput) {
        fileInput.addEventListener('change', () => {
            const target = fileInput.dataset.targetPath ?? '';
            if (fileInput.files?.length) fsUploadFiles(target, fileInput.files);
            fileInput.value = '';
        });
    }
}

async function onFsTreeClick(e) {
    const row = e.target.closest('.fs-row');
    if (!row || row.dataset.inline === '1') return;

    const inlineInput = row.querySelector('.fs-inline-input');
    if (inlineInput) return;

    const moreBtn = e.target.closest('.fs-more-btn');
    if (moreBtn) {
        e.stopPropagation();
        e.preventDefault();
        const rect = moreBtn.getBoundingClientRect();
        openFsContextMenu(
            { clientX: rect.right, clientY: rect.bottom },
            { path: row.dataset.path, type: row.dataset.type, name: row.dataset.name },
        );
        return;
    }

    const path = row.dataset.path;
    const type = row.dataset.type;
    fsState.selected = path;

    if (type === 'dir') {
        if (fsState.expanded.has(path)) {
            fsState.expanded.delete(path);
        } else {
            fsState.expanded.add(path);
            if (!fsState.cache.has(path)) {
                fsSetStatus('…');
                try {
                    await fsFetchList(path);
                } catch (err) {
                    fsSetStatus(err.message);
                    return;
                }
                fsSetStatus('');
            }
        }
        renderTree();
        return;
    }

    document.querySelectorAll('#fs-tree .fs-row').forEach(r => r.classList.remove('is-selected'));
    row.classList.add('is-selected');
}

function onFsTreeDblClick(e) {
    const nameEl = e.target.closest('.fs-name');
    if (!nameEl) return;
    const row = nameEl.closest('.fs-row');
    if (!row || row.dataset.inline === '1') return;
    fsStartRename(row.dataset.path, row.dataset.name);
}

function onFsTreeContextMenu(e) {
    const row = e.target.closest('.fs-row');
    if (!row || row.dataset.inline === '1') return;
    e.preventDefault();
    fsState.selected = row.dataset.path;
    document.querySelectorAll('#fs-tree .fs-row').forEach(r => r.classList.remove('is-selected'));
    row.classList.add('is-selected');
    openFsContextMenu(e, {
        path: row.dataset.path,
        type: row.dataset.type,
        name: row.dataset.name,
    });
}

let fsDragPath = null;

function onFsDragStart(e) {
    if (e.target.closest('.fs-more-btn')) {
        e.preventDefault();
        return;
    }
    const row = e.target.closest('.fs-row[data-path]');
    if (!row || row.dataset.inline === '1') return;
    fsDragPath = row.dataset.path;
    e.dataTransfer.setData('application/x-fs-path', fsDragPath);
    e.dataTransfer.effectAllowed = 'move';
}

function onFsDragEnd() {
    fsDragPath = null;
    document.querySelectorAll('#fs-tree .fs-row.is-drop-target').forEach(r => r.classList.remove('is-drop-target'));
}

function onFsDragOver(e) {
    const tree = document.getElementById('fs-tree');
    if (!tree?.contains(e.target)) return;
    const hasFiles = e.dataTransfer.types.includes('Files');
    const hasInternal = e.dataTransfer.types.includes('application/x-fs-path');
    if (!hasFiles && !hasInternal) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = hasFiles ? 'copy' : 'move';
    document.querySelectorAll('#fs-tree .fs-row.is-drop-target').forEach(r => r.classList.remove('is-drop-target'));
    const dirRow = e.target.closest('.fs-row[data-type="dir"]');
    const fileRow = e.target.closest('.fs-row[data-type="file"]');
    if (dirRow) dirRow.classList.add('is-drop-target');
    else if (fileRow) fileRow.classList.add('is-drop-target');
}

function onFsDragLeave(e) {
    const row = e.target.closest('.fs-row');
    if (row) row.classList.remove('is-drop-target');
}

async function onFsDrop(e) {
    e.preventDefault();
    document.querySelectorAll('#fs-tree .fs-row.is-drop-target').forEach(r => r.classList.remove('is-drop-target'));

    let targetDir = '';
    const dirRow = e.target.closest('.fs-row[data-type="dir"]');
    const fileRow = e.target.closest('.fs-row[data-type="file"]');
    if (dirRow) targetDir = dirRow.dataset.path;
    else if (fileRow) targetDir = fsParentPath(fileRow.dataset.path);

    if (e.dataTransfer.files?.length) {
        await fsUploadFiles(targetDir, e.dataTransfer.files);
        return;
    }

    const src = e.dataTransfer.getData('application/x-fs-path') || fsDragPath;
    if (!src) return;
    const base = fsBasename(src);
    const dst = fsJoinPath(targetDir, base);
    if (src === dst || dst.startsWith(src + '/')) return;
    await fsMove(src, dst);
}

function fsToolbarTargetDir() {
    if (fsState.selected != null && fsState.selected !== '') {
        const row = document.querySelector(`#fs-tree .fs-row[data-path="${CSS.escape(fsState.selected)}"]`);
        if (row?.dataset.type === 'dir') return fsState.selected;
        return fsParentPath(fsState.selected);
    }
    return '';
}

function fsToolbarMkdir() {
    fsState.inlineEdit = { parent: fsToolbarTargetDir(), kind: 'dir', defaultName: 'New Folder' };
    fsState.expanded.add(fsState.inlineEdit.parent);
    renderTree();
    const input = document.querySelector('#fs-tree .fs-inline-input');
    if (input) {
        input.focus();
        input.select();
        input.addEventListener('keydown', (ev) => fsInlineKeydown(ev, 'dir'));
        input.addEventListener('blur', () => fsCommitInline('dir', input));
    }
}

function fsToolbarNewFile() {
    fsState.inlineEdit = { parent: fsToolbarTargetDir(), kind: 'file', defaultName: 'untitled.txt' };
    fsState.expanded.add(fsState.inlineEdit.parent);
    renderTree();
    const input = document.querySelector('#fs-tree .fs-inline-input');
    if (input) {
        input.focus();
        input.select();
        input.addEventListener('keydown', (ev) => fsInlineKeydown(ev, 'file'));
        input.addEventListener('blur', () => fsCommitInline('file', input));
    }
}

function fsToolbarUpload() {
    const input = document.getElementById('fs-file-input');
    if (!input) return;
    input.dataset.targetPath = fsToolbarTargetDir();
    input.click();
}

function fsCollapseAll() {
    fsState.expanded = new Set(['']);
    renderTree();
}

function fsInlineKeydown(e, kind) {
    if (e.key === 'Enter') {
        e.preventDefault();
        fsCommitInline(kind, e.target);
    } else if (e.key === 'Escape') {
        fsState.inlineEdit = null;
        renderTree();
    }
}

async function fsCommitInline(kind, input) {
    if (!fsState.inlineEdit) return;
    const name = (input?.value || '').trim();
    const parent = fsState.inlineEdit.parent;
    fsState.inlineEdit = null;
    if (!name) {
        renderTree();
        return;
    }
    const path = fsJoinPath(parent, name);
    fsSetStatus('…');
    try {
        if (kind === 'dir') {
            const res = await fetch('/api/fs/mkdir', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path }),
            });
            if (!res.ok) throw new Error((await res.json()).error || 'mkdir failed');
            fsState.expanded.add(parent);
            fsState.expanded.add(path);
        } else {
            const fd = new FormData();
            fd.append('path', parent);
            fd.append('files', new Blob([]), name);
            const res = await fetch('/api/fs/upload', { method: 'POST', body: fd });
            if (!res.ok) throw new Error((await res.json()).error || 'create failed');
        }
        await fsFetchList(parent);
        if (parent !== '') await fsFetchList(fsParentPath(parent) || '');
        await fsFetchList('');
        fsState.selected = path;
        renderTree();
    } catch (err) {
        alert(err.message);
        await loadFs();
    }
    fsSetStatus('');
}

async function fsUploadFiles(parentPath, fileList) {
    const fd = new FormData();
    fd.append('path', parentPath || '');
    for (const f of fileList) fd.append('files', f);
    fsSetStatus('Uploading…');
    try {
        const res = await fetch('/api/fs/upload', { method: 'POST', body: fd });
        if (!res.ok) throw new Error((await res.json()).error || 'Upload failed');
        fsState.expanded.add(parentPath || '');
        await loadFs();
    } catch (err) {
        alert(err.message);
    }
    fsSetStatus('');
}

async function fsMove(src, dst) {
    fsSetStatus('Moving…');
    try {
        const res = await fetch('/api/fs/move', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ src, dst }),
        });
        if (!res.ok) throw new Error((await res.json()).error || 'Move failed');
        await loadFs();
    } catch (err) {
        alert(err.message);
    }
    fsSetStatus('');
}

function fsStartRename(path, currentName) {
    const row = document.querySelector(`#fs-tree .fs-row[data-path="${CSS.escape(path)}"]`);
    if (!row) return;
    const nameEl = row.querySelector('.fs-name');
    const input = document.createElement('input');
    input.type = 'text';
    input.value = currentName;
    input.className = 'fs-inline-input flex-1 text-[10px] font-bold border border-primary/30 rounded px-1 py-0.5 min-w-0';
    nameEl.replaceWith(input);
    input.focus();
    input.select();

    const commit = async () => {
        const newName = input.value.trim();
        if (!newName || newName === currentName) {
            renderTree();
            return;
        }
        const parent = fsParentPath(path);
        const dst = fsJoinPath(parent, newName);
        await fsMove(path, dst);
    };

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); commit(); }
        if (e.key === 'Escape') renderTree();
    });
    input.addEventListener('blur', commit);
}

async function fsDelete(path) {
    const label = path || 'this item';
    if (!confirm(`Delete "${label}"?`)) return;
    fsSetStatus('…');
    try {
        const res = await fetch(`/api/fs?path=${encodeURIComponent(path)}`, { method: 'DELETE' });
        if (!res.ok) throw new Error((await res.json()).error || 'Delete failed');
        if (fsState.selected === path || fsState.selected?.startsWith(path + '/')) {
            fsState.selected = fsParentPath(path);
        }
        await loadFs();
    } catch (err) {
        alert(err.message);
    }
    fsSetStatus('');
}

function fsDownload(path) {
    window.location.href = `/api/fs/download?path=${encodeURIComponent(path)}`;
}

function fsCopyPath(path) {
    const full = path ? `streams/${path}` : 'streams';
    navigator.clipboard.writeText(full);
    fsSetStatus('Copied');
    setTimeout(() => fsSetStatus(''), 1500);
}

let fsContextMenuEl = null;

function closeFsContextMenu() {
    if (fsContextMenuEl) {
        fsContextMenuEl.remove();
        fsContextMenuEl = null;
    }
    document.removeEventListener('click', closeFsContextMenu);
}

function openFsContextMenu(e, entry) {
    closeFsContextMenu();
    const menu = document.createElement('div');
    menu.id = 'fs-context-menu';
    const isDir = entry.type === 'dir';
    const items = [
        { label: 'Rename', icon: 'edit', action: () => fsStartRename(entry.path, entry.name) },
        { label: 'Copy Path', icon: 'link', action: () => fsCopyPath(entry.path) },
    ];
    if (!isDir) {
        items.push({ label: 'Download', icon: 'download', action: () => fsDownload(entry.path) });
    }
    if (isDir) {
        items.unshift(
            { label: 'New Folder', icon: 'create_new_folder', action: () => { fsState.selected = entry.path; fsToolbarMkdir(); } },
            { label: 'New File', icon: 'note_add', action: () => { fsState.selected = entry.path; fsToolbarNewFile(); } },
            { label: 'Upload Here', icon: 'upload_file', action: () => { fsState.selected = entry.path; fsToolbarUpload(); } },
        );
    }
    items.push({ label: 'Delete', icon: 'delete', danger: true, action: () => fsDelete(entry.path) });

    menu.innerHTML = items.map(it => `
        <button type="button" class="${it.danger ? 'danger' : ''}">
            <span class="material-symbols-outlined text-[14px]">${it.icon}</span>${it.label}
        </button>`).join('');

    menu.querySelectorAll('button').forEach((btn, i) => {
        btn.addEventListener('click', (ev) => {
            ev.stopPropagation();
            closeFsContextMenu();
            items[i].action();
        });
    });

    document.body.appendChild(menu);
    fsContextMenuEl = menu;
    const x = Math.min(e.clientX, window.innerWidth - menu.offsetWidth - 8);
    const y = Math.min(e.clientY, window.innerHeight - menu.offsetHeight - 8);
    menu.style.left = `${x}px`;
    menu.style.top = `${y}px`;
    setTimeout(() => document.addEventListener('click', closeFsContextMenu), 0);
}

// Init file tree listeners once DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    bindFsTreeEvents();
});

