// ─── Sidebar ────────────────────────────────────────────────
let activeSidePanel = null;

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
    panel.style.transform = 'translateX(0)';
    activeSidePanel = name;

    if (name === 'files') loadStreams();
}

function closeSidePanel() {
    const panel = document.getElementById('side-panel');
    panel.style.transform = 'translateX(-220px)';
    document.querySelectorAll('.sidebar-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.side-panel-content').forEach(p => {
        p.classList.add('hidden');
        p.style.display = '';
    });
    activeSidePanel = null;
}

// Close on click outside
document.addEventListener('click', (e) => {
    if (!activeSidePanel) return;
    const sidebar = document.getElementById('sidebar');
    if (!sidebar.contains(e.target)) closeSidePanel();
});

// Global variable to store current metadata
let currentMetadata = null;

// Listen for dropdown changes
document.getElementById('selected_db_id').addEventListener('change', function(e) {
    updateSchemaPanel(e.target.value);
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
        const response = await fetch(`/api/metadata/${dbId}`);
        const data = await response.json();
        
        renderMetadata(data.metadata);
    } catch (err) {
        treeContainer.innerHTML = `<div class="text-[9px] text-red-400 text-center py-8 font-bold">Failed to load metadata</div>`;
    }
}

function renderMetadata(meta) {
    const treeContainer = document.getElementById('schema-tree');
    const dbNameLabel = document.getElementById('db-name-label');
    const tableCount = document.getElementById('table-count');
    const schemaName = document.getElementById('schema-name');

    // Update Header Stats
    dbNameLabel.innerText = meta.database || 'Postgres';
    tableCount.innerText = meta.table_count || 0;
    schemaName.innerText = meta.schema || 'public';

    let html = '';

    // Loop through tables in the metadata
    Object.entries(meta.tables).forEach(([tableName, details]) => {
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
                ${details.columns.map((col, idx) => `
                    <div class="flex items-center justify-between group/row">
                        <span class="text-[9px] font-bold text-slate-500">${col}</span>
                        <span class="text-[8px] font-mono text-slate-300 group-hover/row:text-primary transition-colors">${details.column_types[col]}</span>
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

// ─── Stream File Manager ──────────────────────────────────────
async function loadStreams() {
    try {
        const res = await fetch('/streams');
        const streams = await res.json();
        renderStreams(streams);
    } catch (e) {
        document.getElementById('stream-list').innerHTML =
            '<div class="text-[9px] text-red-400 text-center py-6 font-bold">Failed to load</div>';
    }
}

function renderStreams(streams) {
    const list = document.getElementById('stream-list');
    if (!streams.length) {
        list.innerHTML = `
            <div class="flex flex-col items-center justify-center py-12 opacity-40">
                <span class="material-symbols-outlined text-[32px] mb-2">folder_off</span>
                <span class="text-[10px] font-medium">No streams in volume</span>
            </div>`;
        return;
    }

    // Update Metadata
    const totalBytes = streams.reduce((acc, s) =>
        acc + Object.values(s.files).reduce((a, f) => a + f.size_bytes, 0), 0);
    document.getElementById('storage-used').textContent = fmtSize(totalBytes);

    list.innerHTML = streams.map(stream => `
        <div class="mb-0.5">
            <div class="flex items-center gap-2 px-2 py-1 hover:bg-slate-50 rounded-md cursor-pointer group"
                 onclick="toggleStreamCard('${stream.name}')">
                <span class="material-symbols-outlined text-[14px] text-slate-300 stream-chevron-${stream.name} transition-transform">arrow_right</span>
                <span class="text-[11px] font-semibold text-slate-600 truncate flex-1">${stream.name}</span>
                <button class="opacity-0 group-hover:opacity-100 text-slate-400 hover:text-red-500 transition-all" 
                        onclick="event.stopPropagation(); deleteStream('${stream.name}')">
                    <span class="material-symbols-outlined text-[14px]">close</span>
                </button>
            </div>
            
            <div id="files-${stream.name}" class="hidden ml-3 pl-2 border-l border-slate-100 space-y-px mt-0.5">
                ${renderFileRow(stream.name, 'source.parquet', stream.files['source.parquet'], false)}
                ${stream.files['working.parquet'] ? renderFileRow(stream.name, 'working.parquet', stream.files['working.parquet'], true) : ''}
            </div>
        </div>
    `).join('');
}

function renderFileRow(streamName, fileName, meta, isMutable) {
    if (!meta) return '';
    
    // Warning: Only appears if data is actually huge relative to memory
    const warning = !meta.memory_safe 
        ? `<span class="material-symbols-outlined text-[13px] text-amber-500/70" title="Batching required">error</span>` 
        : '';

    return `
        <div class="flex items-center gap-2 py-1 px-2 group/file hover:bg-slate-50/80 rounded transition-colors">
            <span class="material-symbols-outlined text-[14px] ${isMutable ? 'text-indigo-400' : 'text-slate-300'}">
                ${isMutable ? 'terminal' : 'database'}
            </span>
            <span class="text-[10px] text-slate-500 flex-1 truncate">${fileName}</span>
            <div class="flex items-center gap-2">
                ${warning}
                <span class="text-[9px] font-mono text-slate-300 opacity-0 group-hover/file:opacity-100">${meta.size_pretty}</span>
                <div class="flex gap-1 opacity-0 group-hover/file:opacity-100">
                    <button class="text-slate-400 hover:text-primary p-0.5" onclick="copyPath('src/temp/${streamName}/${fileName}')" title="Copy Path">
                        <span class="material-symbols-outlined text-[13px]">link</span>
                    </button>
                </div>
            </div>
        </div>`;
}
function toggleStreamCard(name) {
    const files = document.getElementById(`files-${name}`);
    const chevron = document.querySelector(`.stream-chevron-${name}`);
    const isOpen = !files.classList.contains('hidden');
    files.classList.toggle('hidden', isOpen);
    if (chevron) chevron.style.transform = isOpen ? '' : 'rotate(90deg)';
}

async function deleteStream(name) {
    if (!confirm(`Delete stream "${name}" and all its files?`)) return;
    await fetch(`/streams/${name}`, { method: 'DELETE' });
    loadStreams();
}

async function resetStream(name) {
    if (!confirm(`Reset working.parquet to source checkpoint?`)) return;
    await fetch(`/streams/${name}/reset`, { method: 'POST' });
    loadStreams();
}

function downloadFile(streamName, fileName) {
    window.location.href = `/streams/${streamName}/${fileName}`;
}

function copyPath(path) {
    navigator.clipboard.writeText(path);
}

function fmtSize(b) {
    if (b < 1024) return `${b} B`;
    if (b < 1024 ** 2) return `${(b / 1024).toFixed(1)} KB`;
    if (b < 1024 ** 3) return `${(b / 1024 ** 2).toFixed(1)} MB`;
    return `${(b / 1024 ** 3).toFixed(2)} GB`;
}

