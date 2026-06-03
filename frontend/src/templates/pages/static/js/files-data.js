/**
 * File connection preview + pull (files-data panel).
 */
(() => {
    const DEFAULT_PAGE_SIZE = 20;

    let _allRows = [];
    let _currentPage = 0;
    let _pageSize = DEFAULT_PAGE_SIZE;
    let _columnCount = 0;

    function escapeHtml(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function getConnections() {
        return Array.isArray(window.SPORE_CONNECTIONS) ? window.SPORE_CONNECTIONS : [];
    }

    function getActiveConnection(conn) {
        if (conn) return conn;
        const select = document.getElementById('selected_db_id');
        if (!select) return null;
        return getConnections().find(c => String(c.id) === String(select.value)) || null;
    }

    function isFileConnection(conn) {
        if (!conn) return false;
        if (typeof window.resolveDataKind === 'function') {
            return window.resolveDataKind(conn) === 'file';
        }
        const st = String(conn.source_type || '').toLowerCase();
        return st.endsWith('_file') || conn.kind === 'file';
    }

    function setMeta(text) {
        const el = document.getElementById('file-preview-meta');
        if (el) el.textContent = text;
    }

    function resetState() {
        _allRows = [];
        _currentPage = 0;
        _columnCount = 0;
    }

    function pageCount() {
        return Math.max(1, Math.ceil(_allRows.length / _pageSize));
    }

    function clampPage() {
        const pages = pageCount();
        if (_currentPage >= pages) _currentPage = pages - 1;
        if (_currentPage < 0) _currentPage = 0;
    }

    function renderColumns(cols) {
        _columnCount = (cols || []).length;
        const head = document.getElementById('file-preview-head');
        if (!head) return;
        head.innerHTML = (cols || []).map(c => `
            <th class="px-3 py-2 text-left text-[9px] font-black tracking-wider text-slate-500 whitespace-nowrap">${escapeHtml(c)}</th>
        `).join('');
    }

    function rowHtml(row, idx) {
        const stripe = idx % 2 === 0 ? 'bg-white' : 'bg-slate-50/50';
        const cells = Object.values(row).map((v) => {
            const cell = (v === null || v === undefined)
                ? '<span class="text-slate-300 italic">null</span>'
                : escapeHtml(String(v));
            return `<td class="px-3 py-1.5 text-[11px] text-slate-700 font-medium whitespace-nowrap border-b border-slate-100">${cell}</td>`;
        }).join('');
        return `<tr class="${stripe} hover:bg-primary-soft/30 transition-colors">${cells}</tr>`;
    }

    function renderPage() {
        clampPage();
        const body = document.getElementById('file-preview-body');
        if (!body) return;

        const start = _currentPage * _pageSize;
        const pageRows = _allRows.slice(start, start + _pageSize);
        if (pageRows.length === 0) {
            body.innerHTML = '<tr><td class="px-3 py-2 text-slate-400 italic">No rows</td></tr>';
        } else {
            body.innerHTML = pageRows.map((row, i) => rowHtml(row, start + i)).join('');
        }

        const info = document.getElementById('file-preview-pager-info');
        if (info) {
            info.innerHTML = `Page · <span class="text-slate-700">${_currentPage + 1}</span> / ${pageCount()}`;
        }

        const prev = document.getElementById('file-preview-prev');
        const next = document.getElementById('file-preview-next');
        if (prev) prev.disabled = _currentPage <= 0;
        if (next) next.disabled = _currentPage >= pageCount() - 1;
    }

    async function consumePreviewSSE(response) {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let streamedRows = 0;

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

                if (data.type === 'columns') {
                    renderColumns(data.content);
                } else if (data.type === 'rows') {
                    const rows = data.content || [];
                    _allRows.push(...rows);
                    streamedRows += rows.length;
                    renderPage();
                } else if (data.type === 'metadata') {
                    const total = data.total_rows ?? streamedRows;
                    setMeta(`${streamedRows} rows · ${_columnCount} cols · ${total} total`);
                } else if (data.type === 'error') {
                    throw new Error(data.content || 'Preview failed');
                }
            }
        }
    }

    async function runFilePreview(conn) {
        const active = getActiveConnection(conn);
        if (!active || !isFileConnection(active)) return;

        const limitInput = document.getElementById('data-row-limit');
        const limit = parseInt(limitInput?.value || '100', 10) || 100;

        resetState();
        setMeta('Loading…');
        const body = document.getElementById('file-preview-body');
        if (body) {
            body.innerHTML = '<tr><td class="px-3 py-2 text-slate-400 italic">Loading…</td></tr>';
        }

        const formData = new FormData();
        formData.append('query', '');
        formData.append('id', active.id);
        formData.append('limit', String(limit));

        try {
            const response = await fetch('/query-preview', { method: 'POST', body: formData });
            if (!response.ok || !response.body) {
                throw new Error(`HTTP ${response.status}`);
            }
            await consumePreviewSSE(response);
            if (_allRows.length === 0) {
                setMeta(`0 rows · ${_columnCount} cols`);
            }
        } catch (e) {
            setMeta('Preview failed');
            if (body) {
                body.innerHTML = `<tr><td class="px-3 py-2 text-rose-500">${escapeHtml(e.message || String(e))}</td></tr>`;
            }
        }
    }

    async function materializeFilePull() {
        const conn = getActiveConnection();
        if (!conn || !isFileConnection(conn)) return;

        const streamInput = document.getElementById('file-stream-name');
        const streamName = (streamInput?.value || `stream_${conn.id}`).trim() || `stream_${conn.id}`;
        const formatSelect = document.getElementById('file-output-format');
        const outputFormat = (formatSelect?.value || 'parquet').toLowerCase();

        setMeta(`Pulling → ${streamName}…`);

        const formData = new FormData();
        formData.append('query', '');
        formData.append('id', conn.id);
        formData.append('stream_name', streamName);
        formData.append('format', outputFormat);

        try {
            const response = await fetch('/ingest', { method: 'POST', body: formData });
            if (!response.ok || !response.body) {
                throw new Error(`HTTP ${response.status}`);
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let donePath = streamName;

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
                    if (data.type === 'done') {
                        donePath = data.path || streamName;
                    } else if (data.type === 'error') {
                        throw new Error(data.content || 'Pull failed');
                    }
                }
            }

            setMeta(`Pulled → ${donePath}`);
            if (typeof window.registerRelationAfterIngest === 'function') {
                window.registerRelationAfterIngest(streamName, conn.id, '');
            }
            if (typeof window.loadStreams === 'function') {
                try { window.loadStreams(); } catch { /* noop */ }
            }
        } catch (e) {
            setMeta(`Pull failed: ${e.message || e}`);
        }
    }

    function goToFilePreviewPage(dir) {
        if (dir === 'prev') _currentPage -= 1;
        else if (dir === 'next') _currentPage += 1;
        else if (typeof dir === 'number') _currentPage = dir;
        renderPage();
    }

    window.runFilePreview = runFilePreview;
    window.materializeFilePull = materializeFilePull;
    window.goToFilePreviewPage = goToFilePreviewPage;
})();
