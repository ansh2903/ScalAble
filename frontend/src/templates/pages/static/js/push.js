/**
 * Push panel: load a local/volume file into the connected PostgreSQL database.
 *
 * Public API (used by buttons in chat.html):
 *   - setDataMode(mode)       → switch between 'query' and 'push'
 *   - onPushFileSelected(el)  → stage an uploaded file
 *   - openPushVolumePicker()  → list files from the streams volume
 *   - inspectPushFile()         → infer schema + fill DDL editor
 *   - aiAssistPushDdl()         → optional LLM refinement of CREATE TABLE
 *   - pushToDatabase()          → execute DDL + stream file rows (SSE)
 */
(() => {
    let pushDdlEditor = null;
    let stagedToken = null;
    let inspectData = null;

    // ── helpers ─────────────────────────────────────────────────────────────

    function getConnections() {
        return Array.isArray(window.SPORE_CONNECTIONS) ? window.SPORE_CONNECTIONS : [];
    }

    function getActiveConnection() {
        const select = document.getElementById('selected_db_id');
        if (!select) return null;
        const id = select.value;
        return getConnections().find(c => String(c.id) === String(id)) || null;
    }

    function escapeHtml(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function formatBytes(n) {
        if (n === null || n === undefined || Number.isNaN(Number(n))) return null;
        const bytes = Number(n);
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
        return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
    }

    function setPushStatus(text, tone = 'idle') {
        const el = document.getElementById('push-ddl-status');
        if (!el) return;
        el.textContent = text;
        el.classList.remove('text-slate-500', 'text-primary', 'text-amber-400', 'text-rose-400');
        if (tone === 'running') el.classList.add('text-primary');
        else if (tone === 'warn') el.classList.add('text-amber-400');
        else if (tone === 'error') el.classList.add('text-rose-400');
        else el.classList.add('text-slate-500');
    }

    function setFileMeta(text) {
        const el = document.getElementById('push-file-meta');
        if (el) el.textContent = text;
    }

    // ── mode toggle ─────────────────────────────────────────────────────────

    function setDataMode(mode) {
        const isPush = mode === 'push';
        const queryPane = document.getElementById('data-tab-query');
        const pushPane = document.getElementById('data-tab-push');
        const previewPane = document.getElementById('data-tab-preview');
        const hint = document.getElementById('push-mode-hint');

        if (queryPane) queryPane.classList.toggle('hidden', isPush);
        if (pushPane) {
            pushPane.classList.toggle('hidden', !isPush);
            pushPane.classList.toggle('flex', isPush);
        }
        if (previewPane) previewPane.classList.toggle('hidden', isPush);
        if (hint) hint.classList.toggle('hidden', !isPush);

        document.querySelectorAll('.data-mode-tab').forEach((btn) => {
            const active = btn.dataset.dataMode === mode;
            btn.classList.toggle('bg-primary', active);
            btn.classList.toggle('text-white', active);
            btn.classList.toggle('shadow-tactile', active);
            btn.classList.toggle('text-slate-500', !active);
            btn.classList.toggle('hover:text-slate-900', !active);
            btn.classList.toggle('hover:bg-white', !active);
        });

        if (isPush && pushDdlEditor) {
            pushDdlEditor.layout();
        }
    }

    // ── Monaco DDL editor ─────────────────────────────────────────────────────

    function initPushDdlEditor(monaco) {
        const mount = document.getElementById('push-ddl-mount');
        if (!mount || pushDdlEditor) return;

        pushDdlEditor = monaco.editor.create(mount, {
            value: '-- Inspect a file to generate CREATE TABLE DDL\n',
            language: 'sql',
            theme: 'spore-data',
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            automaticLayout: true,
            fontSize: 12,
            fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
            lineNumbers: 'on',
            wordWrap: 'on',
            padding: { top: 10, bottom: 10 },
            tabSize: 2,
        });

        window.pushDdlEditor = pushDdlEditor;
    }

    // ── staging ─────────────────────────────────────────────────────────────

    async function stageUploadedFile(file) {
        const formData = new FormData();
        formData.append('file', file);

        const res = await fetch('/push/stage', { method: 'POST', body: formData });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);

        stagedToken = data.token;
        setFileMeta(`${data.filename} · ${data.size_pretty || formatBytes(data.size)}`);
        inspectData = null;
        return data;
    }

    async function stageVolumePath(path) {
        const res = await fetch('/push/stage', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);

        stagedToken = data.token;
        setFileMeta(`${data.filename} · ${data.size_pretty || formatBytes(data.size)}`);
        inspectData = null;
        return data;
    }

    async function onPushFileSelected(input) {
        const file = input?.files?.[0];
        if (!file) return;

        setPushStatus('Staging…', 'running');
        try {
            await stageUploadedFile(file);
            setPushStatus('Staged — click Inspect', 'idle');
            const tableInput = document.getElementById('push-table-name');
            if (tableInput && !tableInput.value) {
                const base = file.name.replace(/\.[^.]+$/, '').replace(/[^a-zA-Z0-9_]/g, '_');
                tableInput.value = base || 'uploaded_table';
            }
        } catch (e) {
            setPushStatus(`Stage failed: ${e.message}`, 'error');
        }
        input.value = '';
    }

    // ── volume picker ───────────────────────────────────────────────────────

    const PICKABLE_EXT = /\.(csv|tsv|txt|json|ndjson|xls|xlsx|parquet)$/i;

    async function openPushVolumePicker(path = '') {
        const picker = document.getElementById('push-volume-picker');
        const list = document.getElementById('push-volume-list');
        if (!picker || !list) return;

        picker.classList.remove('hidden');
        list.innerHTML = '<div class="px-3 py-2 text-slate-400 italic">Loading…</div>';

        try {
            const url = path
                ? `/api/fs/list?path=${encodeURIComponent(path)}`
                : '/api/fs/list';
            const res = await fetch(url);
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);

            const entries = data.entries || [];
            const dirs = entries.filter(e => e.type === 'dir');
            const files = entries.filter(e => e.type === 'file' && PICKABLE_EXT.test(e.name));

            const rows = [];

            // Breadcrumb / up navigation
            const curPath = data.path || '';
            rows.push(`
                <div class="px-3 py-1.5 bg-slate-50 border-b border-slate-100 flex items-center gap-2 sticky top-0">
                    <span class="material-symbols-outlined text-[13px] text-slate-400">folder</span>
                    <span class="text-[10px] text-slate-500 truncate flex-1">/${escapeHtml(curPath)}</span>
                    ${data.parent !== null && data.parent !== undefined
                        ? `<button type="button" onclick="openPushVolumePicker('${escapeHtml(data.parent)}')" class="text-[9px] font-black uppercase tracking-widest text-primary hover:underline">Up</button>`
                        : ''}
                </div>
            `);

            for (const d of dirs) {
                rows.push(`
                    <button type="button"
                        onclick="openPushVolumePicker('${escapeHtml(d.path)}')"
                        class="w-full text-left px-3 py-2 hover:bg-slate-50 transition-colors flex items-center gap-2">
                        <span class="material-symbols-outlined text-[14px] text-amber-500">${d.is_stream ? 'database' : 'folder'}</span>
                        <span class="text-slate-700 truncate flex-1">${escapeHtml(d.name)}</span>
                        <span class="material-symbols-outlined text-[13px] text-slate-300">chevron_right</span>
                    </button>
                `);
            }

            for (const f of files) {
                rows.push(`
                    <button type="button"
                        onclick="selectPushVolumeFile('${escapeHtml(f.path)}')"
                        class="w-full text-left px-3 py-2 hover:bg-slate-50 transition-colors flex items-center justify-between gap-2">
                        <span class="text-slate-700 truncate flex items-center gap-2">
                            <span class="material-symbols-outlined text-[14px] text-slate-400">draft</span>
                            ${escapeHtml(f.name)}
                        </span>
                        <span class="text-slate-400 shrink-0">${escapeHtml(f.size_pretty || '')}</span>
                    </button>
                `);
            }

            if (dirs.length === 0 && files.length === 0) {
                rows.push('<div class="px-3 py-2 text-slate-400 italic">Empty folder</div>');
            }

            list.innerHTML = rows.join('');
        } catch (e) {
            list.innerHTML = `<div class="px-3 py-2 text-rose-400">${escapeHtml(e.message)}</div>`;
        }
    }

    async function selectPushVolumeFile(path) {
        const pathInput = document.getElementById('push-volume-path');
        const picker = document.getElementById('push-volume-picker');
        if (pathInput) pathInput.value = path;
        if (picker) picker.classList.add('hidden');

        setPushStatus('Staging…', 'running');
        try {
            await stageVolumePath(path);
            setPushStatus('Staged — click Inspect', 'idle');
            const tableInput = document.getElementById('push-table-name');
            if (tableInput && !tableInput.value) {
                const base = path.split('/').pop().replace(/\.[^.]+$/, '').replace(/[^a-zA-Z0-9_]/g, '_');
                tableInput.value = base || 'imported_table';
            }
        } catch (e) {
            setPushStatus(`Stage failed: ${e.message}`, 'error');
        }
    }

    // ── inspect ───────────────────────────────────────────────────────────────

    function renderSchemaOverview(data) {
        const tbody = document.getElementById('push-schema-tbody');
        const sampleEl = document.getElementById('push-sample-rows');

        if (tbody) {
            const cols = data.columns || [];
            const types = data.types || [];
            if (cols.length === 0) {
                tbody.innerHTML = '<tr><td colspan="2" class="px-2 py-4 text-center text-slate-300 italic text-[10px]">No columns detected</td></tr>';
            } else {
                tbody.innerHTML = cols.map((c, i) => `
                    <tr class="border-b border-slate-50 hover:bg-slate-50/50">
                        <td class="px-2 py-1 text-slate-700">${escapeHtml(c)}</td>
                        <td class="px-2 py-1 text-slate-500">${escapeHtml(types[i] || 'TEXT')}</td>
                    </tr>
                `).join('');
            }
        }

        if (sampleEl) {
            const rows = data.sample_rows || [];
            if (rows.length === 0) {
                sampleEl.textContent = '—';
            } else {
                sampleEl.innerHTML = rows.slice(0, 5).map((row, i) => `
                    <div class="py-0.5 border-b border-slate-50 last:border-0 truncate" title="${escapeHtml(JSON.stringify(row))}">
                        <span class="text-slate-400">${i + 1}.</span> ${escapeHtml(JSON.stringify(row))}
                    </div>
                `).join('');
            }
        }
    }

    async function inspectPushFile() {
        const conn = getActiveConnection();
        if (!conn) {
            setPushStatus('Pick a connection first', 'warn');
            return;
        }
        if (conn.source_type !== 'postgresql' && conn.db_type !== 'postgresql') {
            setPushStatus('Push is PostgreSQL-only for now', 'warn');
            return;
        }

        const tableName = (document.getElementById('push-table-name')?.value || '').trim();
        if (!tableName) {
            setPushStatus('Enter a table name', 'warn');
            return;
        }

        if (!stagedToken) {
            const volPath = (document.getElementById('push-volume-path')?.value || '').trim();
            if (volPath) {
                setPushStatus('Staging…', 'running');
                try {
                    await stageVolumePath(volPath);
                } catch (e) {
                    setPushStatus(`Stage failed: ${e.message}`, 'error');
                    return;
                }
            } else {
                setPushStatus('Upload or pick a file first', 'warn');
                return;
            }
        }

        setPushStatus('Inspecting…', 'running');
        try {
            const res = await fetch('/push/inspect', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    token: stagedToken,
                    table_name: tableName,
                    id: conn.id,
                }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);

            inspectData = data;
            renderSchemaOverview(data);

            if (pushDdlEditor && data.suggested_ddl) {
                pushDdlEditor.setValue(data.suggested_ddl);
            }

            const estLabel = data.est_rows != null
                ? ` · ~${Number(data.est_rows).toLocaleString()} rows`
                : '';
            setFileMeta(`${data.filename || 'file'} · ${data.file_size_pretty || ''}${estLabel}`);
            setPushStatus(`${(data.columns || []).length} columns inferred`, 'idle');
        } catch (e) {
            setPushStatus(`Inspect failed: ${e.message}`, 'error');
        }
    }

    // ── AI assist ───────────────────────────────────────────────────────────

    async function aiAssistPushDdl() {
        const conn = getActiveConnection();
        if (!conn) {
            setPushStatus('Pick a connection first', 'warn');
            return;
        }
        if (!stagedToken) {
            setPushStatus('Inspect a file first', 'warn');
            return;
        }

        const tableName = (document.getElementById('push-table-name')?.value || '').trim();
        if (!tableName) {
            setPushStatus('Enter a table name', 'warn');
            return;
        }

        setPushStatus('AI generating DDL…', 'running');
        try {
            const res = await fetch('/push/suggest-ddl', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    token: stagedToken,
                    table_name: tableName,
                    id: conn.id,
                }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);

            if (pushDdlEditor && data.ddl) {
                pushDdlEditor.setValue(data.ddl);
            }
            setPushStatus('AI DDL applied — review before pushing', 'idle');
        } catch (e) {
            setPushStatus(`AI assist failed: ${e.message}`, 'error');
        }
    }

    // ── push execution ──────────────────────────────────────────────────────

    function showPushProgress() {
        const el = document.getElementById('push-progress');
        if (el) el.classList.remove('hidden');
    }

    function hidePushProgress(delayMs = 0) {
        const hide = () => {
            const el = document.getElementById('push-progress');
            if (el) el.classList.add('hidden');
            const bar = document.getElementById('push-progress-bar');
            if (bar) {
                bar.style.width = '0%';
                bar.classList.remove('animate-pulse', 'w-[40%]');
            }
        };
        if (delayMs > 0) setTimeout(hide, delayMs);
        else hide();
    }

    function setPushProgressStage(text, tone = 'primary') {
        const el = document.getElementById('push-progress-stage');
        if (!el) return;
        el.textContent = text;
        el.classList.remove('text-primary', 'text-rose-500');
        el.classList.add(tone === 'error' ? 'text-rose-500' : 'text-primary');
    }

    function setPushProgressDetail(text) {
        const el = document.getElementById('push-progress-detail');
        if (el) el.textContent = text;
    }

    function updatePushProgress(rowsSoFar, bytesSoFar, estRows) {
        const bar = document.getElementById('push-progress-bar');
        if (!bar) return;

        const hasEst = estRows !== null && estRows !== undefined && !Number.isNaN(Number(estRows));
        if (hasEst && Number(estRows) > 0) {
            const pct = Math.min(100, Math.round((rowsSoFar / Number(estRows)) * 100));
            bar.style.width = `${pct}%`;
            bar.classList.remove('animate-pulse', 'w-[40%]');
        } else {
            bar.style.width = '';
            bar.classList.add('animate-pulse', 'w-[40%]');
        }

        const rowsPart = hasEst
            ? `${Number(rowsSoFar).toLocaleString()} / ~${Number(estRows).toLocaleString()} rows`
            : `${Number(rowsSoFar).toLocaleString()} rows`;
        const bytesLabel = formatBytes(bytesSoFar) || '0 B';
        setPushProgressDetail(`${rowsPart} · ${bytesLabel}`);
    }

    async function consumeSSE(response, onEvent) {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                let data;
                try { data = JSON.parse(line.slice(6)); } catch { continue; }
                const stop = onEvent(data);
                if (stop) return;
            }
        }
    }

    async function refreshConnectionMetadata(connId) {
        try {
            const res = await fetch(`/api/metadata/${encodeURIComponent(connId)}`);
            if (!res.ok) return;
            const data = await res.json();
            const conns = getConnections();
            const idx = conns.findIndex(c => String(c.id) === String(connId));
            if (idx >= 0 && data.metadata) {
                conns[idx].metadata = data.metadata;
                window.SPORE_CONNECTIONS = conns;
            }
        } catch { /* noop */ }
    }

    async function pushToDatabase() {
        const conn = getActiveConnection();
        if (!conn) {
            setPushStatus('Pick a connection first', 'warn');
            return;
        }
        if (conn.source_type !== 'postgresql' && conn.db_type !== 'postgresql') {
            setPushStatus('Push is PostgreSQL-only for now', 'warn');
            return;
        }
        if (!stagedToken) {
            setPushStatus('Inspect a file first', 'warn');
            return;
        }

        const tableName = (document.getElementById('push-table-name')?.value || '').trim();
        if (!tableName) {
            setPushStatus('Enter a table name', 'warn');
            return;
        }

        const ddl = pushDdlEditor ? (pushDdlEditor.getValue() || '').trim() : '';
        if (!ddl) {
            setPushStatus('DDL editor is empty — inspect first', 'warn');
            return;
        }

        setPushStatus('Pushing…', 'running');
        showPushProgress();
        setPushProgressStage('Starting…');
        setPushProgressDetail('— rows');
        updatePushProgress(0, 0, inspectData?.est_rows ?? null);

        let estRows = inspectData?.est_rows ?? null;
        let failed = false;

        try {
            const res = await fetch('/push/execute', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    token: stagedToken,
                    table_name: tableName,
                    id: conn.id,
                    ddl,
                }),
            });

            if (!res.ok || !res.body) {
                setPushStatus(`Push failed: HTTP ${res.status}`, 'error');
                setPushProgressStage('Failed', 'error');
                hidePushProgress(3000);
                return;
            }

            await consumeSSE(res, (data) => {
                if (data.type === 'start') {
                    estRows = data.est_total_rows ?? estRows;
                    setPushProgressStage('Creating table & loading…');
                    updatePushProgress(0, 0, estRows);
                } else if (data.type === 'progress') {
                    updatePushProgress(
                        data.rows_so_far ?? 0,
                        data.bytes_so_far ?? 0,
                        estRows,
                    );
                } else if (data.type === 'done') {
                    const bar = document.getElementById('push-progress-bar');
                    if (bar) {
                        bar.classList.remove('animate-pulse', 'w-[40%]');
                        bar.style.width = '100%';
                    }
                    setPushProgressStage('Done');
                    updatePushProgress(
                        data.total_rows ?? 0,
                        data.total_bytes ?? 0,
                        data.total_rows ?? estRows,
                    );
                    setPushStatus(
                        `Pushed ${Number(data.total_rows ?? 0).toLocaleString()} rows → ${tableName}`,
                        'idle',
                    );
                    refreshConnectionMetadata(conn.id);
                    hidePushProgress(2000);
                } else if (data.type === 'error') {
                    failed = true;
                    setPushStatus(`Push failed: ${data.content}`, 'error');
                    setPushProgressStage('Failed', 'error');
                    hidePushProgress(3000);
                    return true;
                }
                return false;
            });

            if (!failed) {
                const bar = document.getElementById('push-progress-bar');
                if (bar && bar.style.width !== '100%') {
                    setPushProgressStage('Done');
                    hidePushProgress(2000);
                }
            }
        } catch (e) {
            setPushStatus(`Push failed: ${e.message}`, 'error');
            setPushProgressStage('Failed', 'error');
            hidePushProgress(3000);
        }
    }

    // ── boot ────────────────────────────────────────────────────────────────

    function boot() {
        if (!window.monacoReady) return;

        window.monacoReady.then((monaco) => {
            initPushDdlEditor(monaco);
        });
    }

    // Expose API for inline handlers in chat.html.
    window.setDataMode = setDataMode;
    window.onPushFileSelected = onPushFileSelected;
    window.openPushVolumePicker = openPushVolumePicker;
    window.selectPushVolumeFile = selectPushVolumeFile;
    window.inspectPushFile = inspectPushFile;
    window.aiAssistPushDdl = aiAssistPushDdl;
    window.pushToDatabase = pushToDatabase;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
})();
