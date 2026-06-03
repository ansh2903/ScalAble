/**
 * Data panel editor: Monaco-backed SQL / NoSQL input wired to
 * /query-preview (preview) and /ingest (pull to local volume).
 *
 * Public API exposed on window (used by buttons in chat.html):
 *   - runDataPreview()         → streams query results into the overlay table
 *   - materializeDataQuery()   → pulls the query result to a local volume
 *   - filterDataResults()      → client-side filter for the result table
 *   - clearDataResultsSearch() → clears the row filter
 *   - setDataPreviewTab(tab)   → switches between 'results' and 'history'
 *   - restoreHistoryEntry(id)  → loads a past query back into the editor
 *   - clearQueryHistory()      → wipes stored history (with confirm)
 */
(() => {
    // Source-type → editor language. Anything not listed falls back to SQL.
    const LANGUAGE_BY_SOURCE_TYPE = {
        postgresql: 'sql',
        bigquery: 'sql',
        snowflake: 'sql',
        mysql: 'sql',
        mssql: 'sql',
        redshift: 'sql',
        mongodb: 'json',
    };

    const DEFAULT_QUERIES = {
        sql:
            'SELECT *\n' +
            'FROM information_schema.tables\n' +
            'LIMIT 100;\n',
        json:
            '{\n' +
            '    "collection": "events",\n' +
            '    "filter": {},\n' +
            '    "limit": 100\n' +
            '}\n',
    };

    let editor = null;
    let currentLanguage = 'sql';

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

    function languageForConnection(conn) {
        if (!conn) return 'sql';
        const sourceType = String(conn.source_type || conn.db_type || '').toLowerCase();
        return LANGUAGE_BY_SOURCE_TYPE[sourceType] || 'sql';
    }

    function setStatus(text, tone = 'idle') {
        const el = document.getElementById('data-editor-status');
        if (!el) return;
        el.textContent = text;
        el.classList.remove('text-slate-500', 'text-primary', 'text-amber-400', 'text-rose-400');
        if (tone === 'running') el.classList.add('text-primary');
        else if (tone === 'warn') el.classList.add('text-amber-400');
        else if (tone === 'error') el.classList.add('text-rose-400');
        else el.classList.add('text-slate-500');
    }

    function setLanguageLabel(lang) {
        const el = document.getElementById('data-editor-lang');
        if (el) el.textContent = lang === 'json' ? 'NoSQL' : 'SQL';
    }

    function setResultMeta(text) {
        const el = document.getElementById('data-result-meta');
        if (el) el.textContent = text;
    }

    // ── Result rows cache + pagination ──────────────────────────────────────
    //
    // We keep the full stream of rows in memory and only render a single page
    // into the DOM at a time. This keeps the table responsive even when the
    // user pulls thousands of rows (large innerHTML / layout cost grows
    // linearly otherwise and freezes the tab).

    const DEFAULT_PAGE_SIZE = 20;

    let _allRows = [];
    let _columnCount = 0;
    let _filteredIndices = null; // null = no filter active
    let _currentPage = 0;
    let _pageSize = DEFAULT_PAGE_SIZE;

    function resetResultsState() {
        _allRows = [];
        _columnCount = 0;
        _filteredIndices = null;
        _currentPage = 0;
    }

    function visibleRowCount() {
        return _filteredIndices ? _filteredIndices.length : _allRows.length;
    }

    function pageCount() {
        const total = visibleRowCount();
        return Math.max(1, Math.ceil(total / _pageSize));
    }

    function clampPage() {
        const pages = pageCount();
        if (_currentPage >= pages) _currentPage = pages - 1;
        if (_currentPage < 0) _currentPage = 0;
    }

    function rowMatchesTerm(row, term) {
        if (!term) return true;
        const values = Object.values(row);
        for (let i = 0; i < values.length; i++) {
            const v = values[i];
            if (v !== null && v !== undefined && String(v).toLowerCase().includes(term)) {
                return true;
            }
        }
        return false;
    }

    function clearResultTable() {
        const head = document.getElementById('data-result-head-row');
        const body = document.getElementById('data-result-tbody');
        if (head) head.innerHTML = '';
        if (body) body.innerHTML = '';
        resetResultsState();
        renderPager();
        updateMatchCounter();
    }

    function renderColumns(cols) {
        _columnCount = (cols || []).length;
        const head = document.getElementById('data-result-head-row');
        if (!head) return;
        head.innerHTML = (cols || []).map(c => `
            <th class="px-3 py-2 text-left text-[9px] font-black tracking-wider text-slate-500 whitespace-nowrap">${escapeHtml(c)}</th>
        `).join('');
    }

    function rowHtml(row, globalIndex) {
        const stripe = globalIndex % 2 === 0 ? 'bg-white' : 'bg-slate-50/50';
        const cells = Object.values(row).map((v) => {
            const cell = (v === null || v === undefined)
                ? '<span class="text-slate-300 italic">null</span>'
                : escapeHtml(String(v));
            return `<td class="px-3 py-1.5 text-[11px] text-slate-700 font-medium whitespace-nowrap border-b border-slate-100">${cell}</td>`;
        }).join('');
        return `<tr class="${stripe} hover:bg-primary-soft/30 transition-colors">${cells}</tr>`;
    }

    function renderCurrentPage() {
        clampPage();
        const body = document.getElementById('data-result-tbody');
        if (!body) return;

        const start = _currentPage * _pageSize;
        const end = start + _pageSize;

        let html;
        if (_filteredIndices) {
            const pageIdx = _filteredIndices.slice(start, end);
            html = pageIdx.map(idx => rowHtml(_allRows[idx], idx)).join('');
        } else {
            const pageRows = _allRows.slice(start, end);
            html = pageRows.map((row, i) => rowHtml(row, start + i)).join('');
        }

        body.innerHTML = html;
        renderPager();
        updateMatchCounter();
    }

    function renderPager() {
        const pager = document.getElementById('data-result-pager');
        if (!pager) return;

        const total = visibleRowCount();
        const pages = pageCount();
        clampPage();

        if (_allRows.length === 0) {
            pager.classList.add('hidden');
            pager.classList.remove('flex');
            return;
        }

        const isOnResults = !document.getElementById('data-results-pane')?.classList.contains('hidden');
        pager.classList.toggle('hidden', !isOnResults);
        pager.classList.toggle('flex', isOnResults);

        const info = document.getElementById('data-result-pager-info');
        if (info) {
            if (total === 0) {
                info.textContent = 'No matches';
            } else {
                const startN = _currentPage * _pageSize + 1;
                const endN = Math.min(total, (_currentPage + 1) * _pageSize);
                info.textContent = `${startN.toLocaleString()}–${endN.toLocaleString()} of ${total.toLocaleString()}`;
            }
        }

        const pageLabel = document.getElementById('data-result-pager-page');
        if (pageLabel) pageLabel.textContent = `Page ${_currentPage + 1} / ${pages}`;

        const atFirst = _currentPage === 0;
        const atLast = (_currentPage + 1) >= pages;
        const first = document.getElementById('data-result-pager-first');
        const prev = document.getElementById('data-result-pager-prev');
        const next = document.getElementById('data-result-pager-next');
        const last = document.getElementById('data-result-pager-last');
        if (first) first.disabled = atFirst;
        if (prev) prev.disabled = atFirst;
        if (next) next.disabled = atLast;
        if (last) last.disabled = atLast;

        const sizeSelect = document.getElementById('data-result-page-size');
        if (sizeSelect && String(sizeSelect.value) !== String(_pageSize)) {
            sizeSelect.value = String(_pageSize);
        }
    }

    function goToDataResultsPage(target) {
        const pages = pageCount();
        let page;
        if (target === 'prev') page = _currentPage - 1;
        else if (target === 'next') page = _currentPage + 1;
        else if (target === 'last') page = pages - 1;
        else page = Number(target);

        if (!Number.isFinite(page)) return;
        if (page < 0 || page >= pages) return;
        _currentPage = page;
        renderCurrentPage();
    }

    function setDataResultsPageSize(size) {
        if (!Number.isFinite(size) || size <= 0) return;
        // Try to keep the user roughly anchored at the same row offset.
        const firstVisibleGlobal = _currentPage * _pageSize;
        _pageSize = size;
        _currentPage = Math.floor(firstVisibleGlobal / _pageSize);
        renderCurrentPage();
    }

    function appendRows(rows) {
        if (!rows || rows.length === 0) return;

        const prevVisibleCount = visibleRowCount();
        const startIndex = _allRows.length;
        for (let i = 0; i < rows.length; i++) _allRows.push(rows[i]);

        // Extend the filtered set incrementally so we don't rescan everything
        // on every streaming batch.
        if (_filteredIndices) {
            const term = getResultSearchTerm();
            for (let i = 0; i < rows.length; i++) {
                const idx = startIndex + i;
                if (rowMatchesTerm(_allRows[idx], term)) _filteredIndices.push(idx);
            }
        }

        // Only redraw the body when the new rows would actually land on the
        // current page. Otherwise just refresh the pager/match counter — much
        // cheaper during high-throughput streaming.
        const currentPageEnd = (_currentPage + 1) * _pageSize;
        if (prevVisibleCount < currentPageEnd) {
            renderCurrentPage();
        } else {
            renderPager();
            updateMatchCounter();
        }
    }

    function hasKnownTotal(dbTotalRows) {
        return dbTotalRows !== null
            && dbTotalRows !== undefined
            && dbTotalRows !== 'unknown'
            && !Number.isNaN(Number(dbTotalRows));
    }

    function formatBytes(n) {
        if (n === null || n === undefined || Number.isNaN(Number(n))) return null;
        const bytes = Number(n);
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
        return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
    }

    function formatSizeSuffix(dbEstBytes) {
        const label = formatBytes(dbEstBytes);
        return label ? ` (~${label})` : '';
    }

    function formatStreamingMeta(streamedRows, dbTotalRows, dbEstBytes) {
        const showing = `Showing ${Number(streamedRows).toLocaleString()}`;
        if (!hasKnownTotal(dbTotalRows)) return showing;
        return `Total: ${Number(dbTotalRows).toLocaleString()}${formatSizeSuffix(dbEstBytes)} · ${showing}`;
    }

    function formatFinalMeta(streamedRows, dbTotalRows, dbEstBytes, columnCount, elapsedMs) {
        const parts = [];
        if (hasKnownTotal(dbTotalRows)) {
            parts.push(`Total: ${Number(dbTotalRows).toLocaleString()}${formatSizeSuffix(dbEstBytes)}`);
        }
        parts.push(`Showing ${Number(streamedRows).toLocaleString()}`);
        parts.push(`${columnCount} cols`);
        parts.push(`${elapsedMs.toLocaleString()} ms`);
        return parts.join(' · ');
    }

    // ── Limit input ─────────────────────────────────────────────────────────

    const LIMIT_MIN = 1;
    const LIMIT_MAX = 100_000;

    function readPreviewLimit() {
        const input = document.getElementById('data-row-limit');
        const raw = (input?.value ?? '').trim();
        const parsed = parseInt(raw, 10);
        if (!Number.isFinite(parsed)) return { ok: false, value: parsed, input };
        if (parsed < LIMIT_MIN || parsed > LIMIT_MAX) return { ok: false, value: parsed, input };
        return { ok: true, value: parsed, input };
    }

    // ── Result table client-side filter ─────────────────────────────────────

    function getResultSearchTerm() {
        const input = document.getElementById('data-result-search');
        return (input?.value || '').trim().toLowerCase();
    }

    function applyResultFilter() {
        const term = getResultSearchTerm();
        if (!term) {
            _filteredIndices = null;
        } else {
            _filteredIndices = [];
            for (let i = 0; i < _allRows.length; i++) {
                if (rowMatchesTerm(_allRows[i], term)) _filteredIndices.push(i);
            }
        }
        _currentPage = 0;
        renderCurrentPage();
    }

    function updateMatchCounter() {
        const el = document.getElementById('data-result-match');
        if (!el) return;

        const total = _allRows.length;
        if (total === 0) {
            el.textContent = '— matches';
            return;
        }
        if (_filteredIndices === null) {
            el.textContent = `${total.toLocaleString()} rows`;
        } else {
            el.textContent = `${_filteredIndices.length.toLocaleString()} / ${total.toLocaleString()} match`;
        }
    }

    function filterDataResults() {
        applyResultFilter();
    }

    function clearDataResultsSearch() {
        const input = document.getElementById('data-result-search');
        if (input) input.value = '';
        applyResultFilter();
    }

    function escapeHtml(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    // ── Query history (workspace-scoped via API) ─────────────────────────────

    const HISTORY_LIMIT = 50;
    let _historyCache = [];

    function historyApiBase() {
        const wid = typeof window.getActiveWorkspaceId === 'function'
            ? window.getActiveWorkspaceId()
            : null;
        if (!wid) return null;
        return `/api/workspaces/${encodeURIComponent(wid)}/history`;
    }

    function loadHistory() {
        return _historyCache;
    }

    async function fetchHistoryFromServer() {
        const base = historyApiBase();
        if (!base) {
            _historyCache = [];
            return _historyCache;
        }
        try {
            const res = await fetch(base);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            _historyCache = Array.isArray(data.history) ? data.history : [];
        } catch (e) {
            console.warn('history fetch failed', e);
            _historyCache = _historyCache || [];
        }
        return _historyCache;
    }

    async function pushHistoryEntry(entry) {
        const payload = {
            id: `q_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
            timestamp: Date.now(),
            ...entry,
        };
        const base = historyApiBase();
        if (base) {
            try {
                const res = await fetch(base, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                if (res.ok) {
                    const data = await res.json();
                    if (data.entry) {
                        _historyCache.unshift(data.entry);
                        _historyCache = _historyCache.slice(0, HISTORY_LIMIT);
                        renderQueryHistory();
                        return;
                    }
                }
            } catch (e) {
                console.warn('history save failed, using cache', e);
            }
        }
        _historyCache.unshift(payload);
        _historyCache = _historyCache.slice(0, HISTORY_LIMIT);
        renderQueryHistory();
    }

    function relativeTime(ts) {
        const diff = Math.max(0, (Date.now() - ts) / 1000);
        if (diff < 45) return 'just now';
        if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
        if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
        if (diff < 604800) return `${Math.round(diff / 86400)}d ago`;
        return new Date(ts).toLocaleString();
    }

    function setHistoryCount(n) {
        const el = document.getElementById('data-history-count');
        if (!el) return;
        el.textContent = String(n);
        el.classList.toggle('bg-primary-soft', n > 0);
        el.classList.toggle('text-primary-dark', n > 0);
        el.classList.toggle('bg-slate-200', n === 0);
        el.classList.toggle('text-slate-600', n === 0);
    }

    function renderQueryHistory() {
        const list = document.getElementById('data-history-list');
        const empty = document.getElementById('data-history-empty');
        if (!list || !empty) return;

        const history = loadHistory();
        setHistoryCount(history.length);

        if (history.length === 0) {
            list.innerHTML = '';
            empty.classList.remove('hidden');
            empty.classList.add('flex');
            return;
        }
        empty.classList.add('hidden');
        empty.classList.remove('flex');

        list.innerHTML = history.map((h) => {
            const langLabel = h.language === 'json' ? 'NoSQL' : 'SQL';
            const isOk = h.status === 'success';
            const statusBadge = isOk
                ? `<span class="inline-flex items-center gap-1 h-5 px-2 rounded-pill bg-primary-soft border border-primary/20 text-[8px] font-black uppercase tracking-widest text-primary-dark">
                       <span class="w-1.5 h-1.5 rounded-pill bg-primary"></span>OK
                   </span>`
                : `<span class="inline-flex items-center gap-1 h-5 px-2 rounded-pill bg-rose-50 border border-rose-200 text-[8px] font-black uppercase tracking-widest text-rose-500">
                       <span class="w-1.5 h-1.5 rounded-pill bg-rose-500"></span>Error
                   </span>`;
            const shown = Number(h.rowCount ?? 0).toLocaleString();
            const sizeLabel = h.estTotalBytes ? ` (~${formatBytes(h.estTotalBytes)})` : '';
            const rowsLabel = (h.totalRows !== null && h.totalRows !== undefined)
                ? `${shown} / ${Number(h.totalRows).toLocaleString()}${sizeLabel} rows`
                : `${shown} rows`;
            const stats = isOk
                ? `${rowsLabel} · ${h.colCount ?? 0} cols · ${(h.elapsedMs ?? 0).toLocaleString()} ms`
                : (h.errorMessage || 'Query failed');

            return `
                <div class="group flex flex-col gap-1.5 px-3 py-3 hover:bg-slate-50/80 transition-colors cursor-pointer"
                    onclick="restoreHistoryEntry('${h.id}')"
                    title="Click to restore in the editor">
                    <div class="flex items-center justify-between gap-2 min-w-0">
                        <div class="flex items-center gap-2 min-w-0">
                            ${statusBadge}
                            <span class="inline-flex items-center h-5 px-2 rounded-pill bg-slate-50 border border-slate-200 text-[8px] font-black uppercase tracking-widest text-slate-500">
                                ${langLabel}
                            </span>
                            <span class="text-[9px] font-mono text-slate-500 truncate">
                                ${escapeHtml(h.connectionLabel || '—')}
                            </span>
                        </div>
                        <div class="flex items-center gap-2 shrink-0">
                            <span class="text-[9px] font-mono text-slate-400">${escapeHtml(relativeTime(h.timestamp))}</span>
                            <button type="button"
                                onclick="event.stopPropagation(); restoreHistoryEntry('${h.id}')"
                                class="opacity-0 group-hover:opacity-100 inline-flex items-center gap-1 h-6 px-2 rounded-pill bg-white border border-slate-200 text-[9px] font-black uppercase tracking-widest text-slate-600 hover:text-primary hover:border-primary/40 transition-all">
                                <span class="material-symbols-outlined text-[12px]">arrow_upward</span>
                                Restore
                            </button>
                        </div>
                    </div>
                    <pre class="text-[10.5px] font-mono text-slate-700 whitespace-pre-wrap line-clamp-2 leading-snug m-0">${escapeHtml(h.query || '')}</pre>
                    <span class="text-[9px] font-mono ${isOk ? 'text-slate-400' : 'text-rose-400'}">${escapeHtml(stats)}</span>
                </div>
            `;
        }).join('');
    }

    function restoreHistoryEntry(id) {
        const entry = loadHistory().find((h) => h.id === id);
        if (!entry || !editor) return;
        editor.setValue(entry.query || '');
        editor.focus();
        setDataPreviewTab('results');
        setStatus('Query restored', 'idle');
    }

    async function clearQueryHistory() {
        if (!window.confirm('Clear all saved query history for this workspace?')) return;
        const base = historyApiBase();
        if (base) {
            try {
                await fetch(base, { method: 'DELETE' });
            } catch (e) {
                console.warn('history clear failed', e);
            }
        }
        _historyCache = [];
        renderQueryHistory();
    }

    async function hydrateDataHistoryFromWorkspace() {
        await fetchHistoryFromServer();
        renderQueryHistory();
    }

    function setDataPreviewTab(tab) {
        const showResults = tab !== 'history';

        const resultsPane = document.getElementById('data-results-pane');
        const historyPane = document.getElementById('data-history-pane');
        const resultsCtrl = document.getElementById('data-tab-controls-results');
        const historyCtrl = document.getElementById('data-tab-controls-history');
        const pager = document.getElementById('data-result-pager');

        if (resultsPane) resultsPane.classList.toggle('hidden', !showResults);
        if (historyPane) historyPane.classList.toggle('hidden', showResults);
        if (resultsCtrl) {
            resultsCtrl.classList.toggle('hidden', !showResults);
            resultsCtrl.classList.toggle('flex', showResults);
        }
        if (historyCtrl) {
            historyCtrl.classList.toggle('hidden', showResults);
            historyCtrl.classList.toggle('flex', !showResults);
        }
        if (pager) {
            // Only show the pager when results tab is active AND we have rows
            // to paginate. renderPager() handles the row-count side; we handle
            // the tab side here.
            if (showResults && _allRows.length > 0) {
                pager.classList.remove('hidden');
                pager.classList.add('flex');
            } else {
                pager.classList.add('hidden');
                pager.classList.remove('flex');
            }
        }

        document.querySelectorAll('.data-preview-tab').forEach((btn) => {
            const isActive = btn.dataset.dataTab === (showResults ? 'results' : 'history');
            btn.classList.toggle('bg-primary', isActive);
            btn.classList.toggle('text-white', isActive);
            btn.classList.toggle('shadow-tactile', isActive);
            btn.classList.toggle('text-slate-500', !isActive);
            btn.classList.toggle('hover:text-slate-900', !isActive);
            btn.classList.toggle('hover:bg-white', !isActive);
        });

        if (!showResults) renderQueryHistory();
    }

    // ── Monaco setup ────────────────────────────────────────────────────────

    function initEditor(monaco) {
        const mount = document.getElementById('data-editor-mount');
        if (!mount) return;

        window.monaco = monaco; 
    
        // Use the explicit monaco instance passed to ensure it hooks into the right registry
        if (!window.__sporeDataThemeReady) {
            window.__sporeDataThemeReady = true;
            
            // Define it directly on whatever monaco object is active here
            monaco.editor.defineTheme('spore-data', {
                base: 'vs-dark',
                inherit: true,
                rules: [
                    { token: 'keyword', foreground: '34d399', fontStyle: 'bold' },
                    { token: 'keyword.sql', foreground: '34d399', fontStyle: 'bold' },
                    { token: 'string', foreground: 'a7f3d0' },
                    { token: 'string.sql', foreground: 'a7f3d0' },
                    { token: 'number', foreground: 'fde68a' },
                    { token: 'operator', foreground: '94a3b8' },
                    { token: 'comment', foreground: '64748b', fontStyle: 'italic' },
                    { token: 'identifier', foreground: 'e2e8f0' },
                    { token: 'predefined.sql', foreground: '7dd3fc' },
                ],
                colors: {
                    'editor.background': '#0f172a',
                    'editor.foreground': '#e2e8f0',
                    'editorCursor.foreground': '#00A36C',
                    'editor.lineHighlightBackground': '#1e293b',
                    'editorLineNumber.foreground': '#475569',
                    'editorLineNumber.activeForeground': '#94a3b8',
                    'editor.selectionBackground': '#065f46',
                    'editor.inactiveSelectionBackground': '#064e3b',
                    'editorIndentGuide.background': '#1e293b',
                    'editorIndentGuide.activeBackground': '#334155',
                    'editorWidget.background': '#0f172a',
                    'editorWidget.border': '#1e293b',
                    'editorSuggestWidget.background': '#0f172a',
                    'editorSuggestWidget.border': '#1e293b',
                    'editorSuggestWidget.foreground': '#e2e8f0',
                    'editorSuggestWidget.selectedBackground': '#065f46',
                },
            });
        }
    
        const lang = languageForConnection(getActiveConnection());
        currentLanguage = lang;
        setLanguageLabel(lang);
    
        editor = monaco.editor.create(mount, {
            value: DEFAULT_QUERIES[lang],
            language: lang === 'json' ? 'json' : 'sql',
            theme: 'spore-data', // Now guaranteed to be found in the current context!
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            automaticLayout: true,
            fontSize: 12,
            fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
            lineNumbers: 'on',
            renderLineHighlight: 'line',
            wordWrap: 'on',
            padding: { top: 10, bottom: 10 },
            tabSize: 2,
            smoothScrolling: true,
            scrollbar: { vertical: 'auto', horizontal: 'auto' },
        });
    
        editor.addCommand(monaco.KeyMod.Ctrl & monaco.KeyCode.Enter, () => runDataPreview());

        editor.onDidFocusEditorText(() => monaco.editor.setTheme('spore-data'));

        mount.addEventListener('keydown', (e) => {
            if (e.key !== 'Enter') return;
            if (!e.ctrlKey && !e.metaKey) return;
            if (!window.dataEditor || !window.dataEditor.hasWidgetFocus()) return;
            e.preventDefault();
            e.stopPropagation();
            runDataPreview();
        });
    
        window.dataEditor = editor;
    }

    function setEditorLanguage(lang) {
        if (!editor || !window.monaco) {
            currentLanguage = lang;
            setLanguageLabel(lang);
            return;
        }
        if (currentLanguage === lang) return;

        const model = editor.getModel();
        if (!model) return;

        window.monaco.editor.setModelLanguage(model, lang === 'json' ? 'json' : 'sql');

        // Swap the default boilerplate if the user hasn't started typing.
        const current = (model.getValue() || '').trim();
        const previousDefault = (DEFAULT_QUERIES[currentLanguage] || '').trim();
        if (!current || current === previousDefault) {
            editor.setValue(DEFAULT_QUERIES[lang]);
        }

        currentLanguage = lang;
        setLanguageLabel(lang);
    }

    function syncEditorWithConnection() {
        const conn = getActiveConnection();
        setEditorLanguage(languageForConnection(conn));
    }

    // ── Run / materialize ───────────────────────────────────────────────────

    async function runDataPreview() {

        if (!window.dataEditor || !window.dataEditor.hasWidgetFocus()) {
            return;
        }

        if (!window.dataEditor) return;
        editor.layout();
        editor.focus();

        const conn = getActiveConnection();
        if (!conn) {
            setStatus('Pick a connection first', 'warn');
            return;
        }

        const query = (editor.getValue() || '').trim();
        if (!query) {
            setStatus('Editor is empty', 'warn');
            return;
        }

        const { ok, value: limit, input: limitInput } = readPreviewLimit();
        if (!ok) {
            setStatus(`Limit must be a whole number between ${LIMIT_MIN} and ${LIMIT_MAX.toLocaleString()}`, 'warn');
            limitInput?.focus();
            limitInput?.select?.();
            return;
        }
        // Snap the input back to the parsed value so the user sees what we sent.
        if (limitInput) limitInput.value = String(limit);

        setStatus('Running…', 'running');
        clearResultTable();
        setResultMeta('— rows · — cols · — ms');

        // Reset any active row filter so new rows aren't hidden by stale text.
        const searchInput = document.getElementById('data-result-search');
        if (searchInput) searchInput.value = '';
        updateMatchCounter(0, 0);

        const formData = new FormData();
        formData.append('query', query);
        formData.append('id', conn.id);
        formData.append('limit', String(limit));

        let streamedRows = 0;
        let dbTotalRows = null;
        let dbEstBytes = null;
        let columnCount = 0;
        const t0 = performance.now();

        // Snapshot connection/language for the history entry — these can change
        // mid-run if the user switches the dropdown.
        const historyBase = {
            query,
            limit,
            language: currentLanguage,
            connectionId: conn.id,
            connectionLabel: conn.display_name || conn.name || conn.alias || conn.id,
        };

        try {
            const response = await fetch('/query-preview', { method: 'POST', body: formData });
            if (!response.ok || !response.body) {
                setStatus(`HTTP ${response.status}`, 'error');
                pushHistoryEntry({
                    ...historyBase,
                    status: 'error',
                    errorMessage: `HTTP ${response.status}`,
                    elapsedMs: Math.round(performance.now() - t0),
                });
                return;
            }

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

                    if (data.type === 'columns') {
                        renderColumns(data.content);
                        columnCount = data.content.length;
                    } else if (data.type === 'metadata') {
                        dbTotalRows = data.total_rows;
                        dbEstBytes = data.est_total_bytes ?? null;
                    } else if (data.type === 'rows') {
                        streamedRows += (data.content || []).length;
                        appendRows(data.content);
                        setResultMeta(formatStreamingMeta(streamedRows, dbTotalRows, dbEstBytes));
                    } else if (data.type === 'error') {
                        setStatus(`Error: ${data.content}`, 'error');
                        setResultMeta('Query failed');
                        pushHistoryEntry({
                            ...historyBase,
                            status: 'error',
                            errorMessage: String(data.content || 'Query failed'),
                            elapsedMs: Math.round(performance.now() - t0),
                        });
                        return;
                    }
                }
            }

            const elapsed = Math.round(performance.now() - t0);
            setResultMeta(formatFinalMeta(streamedRows, dbTotalRows, dbEstBytes, columnCount, elapsed));
            setStatus('Done', 'idle');

            pushHistoryEntry({
                ...historyBase,
                status: 'success',
                rowCount: streamedRows,
                totalRows: hasKnownTotal(dbTotalRows) ? Number(dbTotalRows) : null,
                estTotalBytes: dbEstBytes != null ? Number(dbEstBytes) : null,
                colCount: columnCount,
                elapsedMs: elapsed,
            });
        } catch (e) {
            const message = e?.message || String(e);
            setStatus(`Failed: ${message}`, 'error');
            pushHistoryEntry({
                ...historyBase,
                status: 'error',
                errorMessage: message,
                elapsedMs: Math.round(performance.now() - t0),
            });
        }
    }

    // ── Pull progress overlay ───────────────────────────────────────────────

    function showPullProgress() {
        const el = document.getElementById('data-pull-progress');
        if (el) el.classList.remove('hidden');
    }

    function hidePullProgress(delayMs = 0) {
        const hide = () => {
            const el = document.getElementById('data-pull-progress');
            if (el) el.classList.add('hidden');
            const bar = document.getElementById('data-pull-bar');
            if (bar) {
                bar.style.width = '0%';
                bar.classList.remove('animate-pulse', 'w-[40%]');
            }
        };
        if (delayMs > 0) setTimeout(hide, delayMs);
        else hide();
    }

    function setPullStage(text, tone = 'primary') {
        const el = document.getElementById('data-pull-stage');
        if (!el) return;
        el.textContent = text;
        el.classList.remove('text-primary', 'text-rose-500');
        el.classList.add(tone === 'error' ? 'text-rose-500' : 'text-primary');
    }

    function setPullDetail(text) {
        const el = document.getElementById('data-pull-detail');
        if (el) el.textContent = text;
    }

    function updatePullProgress(rowsSoFar, bytesSoFar, estRows, estBytes) {
        const bar = document.getElementById('data-pull-bar');
        if (!bar) return;

        const hasEstRows = estRows !== null && estRows !== undefined && !Number.isNaN(Number(estRows));
        if (hasEstRows && Number(estRows) > 0) {
            const pct = Math.min(100, Math.round((rowsSoFar / Number(estRows)) * 100));
            bar.style.width = `${pct}%`;
            bar.classList.remove('animate-pulse', 'w-[40%]');
        } else {
            bar.style.width = '';
            bar.classList.add('animate-pulse', 'w-[40%]');
        }

        const rowsPart = hasEstRows
            ? `${Number(rowsSoFar).toLocaleString()} / ~${Number(estRows).toLocaleString()} rows`
            : `${Number(rowsSoFar).toLocaleString()} rows`;
        const bytesLabel = formatBytes(bytesSoFar) || '0 B';
        const estBytesLabel = estBytes != null ? formatBytes(estBytes) : null;
        const bytesPart = estBytesLabel
            ? `${bytesLabel} / ~${estBytesLabel}`
            : bytesLabel;
        setPullDetail(`${rowsPart} · ${bytesPart}`);
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

    async function materializeDataQuery() {
        if (!editor) return;

        const conn = getActiveConnection();
        if (!conn) {
            setStatus('Pick a connection first', 'warn');
            return;
        }

        const query = (editor.getValue() || '').trim();
        if (!query) {
            setStatus('Editor is empty', 'warn');
            return;
        }

        const streamInput = document.getElementById('data-stream-name');
        const streamName = (streamInput?.value || `stream_${conn.id}`).trim() || `stream_${conn.id}`;

        const formatSelect = document.getElementById('data-output-format');
        const outputFormat = (formatSelect?.value || 'parquet').toLowerCase();

        setStatus(`Pulling → ${streamName} (${outputFormat})…`, 'running');
        showPullProgress();
        setPullStage('Starting…');
        setPullDetail('— rows');
        updatePullProgress(0, 0, null, null);

        const formData = new FormData();
        formData.append('query', query);
        formData.append('id', conn.id);
        formData.append('stream_name', streamName);
        formData.append('format', outputFormat);

        let estRows = null;
        let estBytes = null;
        let donePath = streamName;

        try {
            const response = await fetch('/ingest', { method: 'POST', body: formData });
            if (!response.ok || !response.body) {
                setStatus(`Pull failed: HTTP ${response.status}`, 'error');
                setPullStage('Failed', 'error');
                hidePullProgress(3000);
                return;
            }

            let failed = false;

            await consumeSSE(response, (data) => {
                if (data.type === 'start') {
                    estRows = data.est_total_rows ?? null;
                    estBytes = data.est_total_bytes ?? null;
                    setPullStage('Pulling');
                    updatePullProgress(0, 0, estRows, estBytes);
                } else if (data.type === 'progress') {
                    updatePullProgress(
                        data.rows_so_far ?? 0,
                        data.bytes_so_far ?? 0,
                        estRows,
                        estBytes,
                    );
                } else if (data.type === 'done') {
                    donePath = data.path || streamName;
                    const bar = document.getElementById('data-pull-bar');
                    if (bar) {
                        bar.classList.remove('animate-pulse', 'w-[40%]');
                        bar.style.width = '100%';
                    }
                    setPullStage('Done');
                    updatePullProgress(
                        data.total_rows ?? 0,
                        data.total_bytes ?? 0,
                        data.total_rows ?? estRows,
                        data.total_bytes ?? estBytes,
                    );
                    setStatus(`Pulled → ${donePath}`, 'idle');
                    if (typeof window.registerRelationAfterIngest === 'function') {
                        window.registerRelationAfterIngest(streamName, conn.id, query);
                    }
                    if (typeof window.loadStreams === 'function') {
                        try { window.loadStreams(); } catch { /* noop */ }
                    }
                    hidePullProgress(1200);
                } else if (data.type === 'error') {
                    failed = true;
                    setStatus(`Pull failed: ${data.content}`, 'error');
                    setPullStage('Failed', 'error');
                    hidePullProgress(3000);
                    return true;
                }
                return false;
            });

            if (!failed) {
                const bar = document.getElementById('data-pull-bar');
                if (bar && bar.style.width !== '100%') {
                    // Legacy connectors may emit only done without progress.
                    setPullStage('Done');
                    setStatus(`Pulled → ${donePath}`, 'idle');
                    if (typeof window.registerRelationAfterIngest === 'function') {
                        window.registerRelationAfterIngest(streamName, conn.id, query);
                    }
                    if (typeof window.loadStreams === 'function') {
                        try { window.loadStreams(); } catch { /* noop */ }
                    }
                    hidePullProgress(1200);
                }
            }
        } catch (e) {
            setStatus(`Pull failed: ${e.message || e}`, 'error');
            setPullStage('Failed', 'error');
            hidePullProgress(3000);
        }
    }

    // ── boot ────────────────────────────────────────────────────────────────

    function boot() {
        hydrateDataHistoryFromWorkspace();

        if (!window.monacoReady) {
            return;
        }

        window.monacoReady.then((monaco) => {
            initEditor(monaco);

            const select = document.getElementById('selected_db_id');
            if (select) {
                select.addEventListener('change', () => syncEditorWithConnection());
            }
            syncEditorWithConnection();
        });
    }

    // Expose the API for inline button onclick handlers in chat.html.
    window.runDataPreview = runDataPreview;
    window.materializeDataQuery = materializeDataQuery;
    window.filterDataResults = filterDataResults;
    window.clearDataResultsSearch = clearDataResultsSearch;
    window.setDataPreviewTab = setDataPreviewTab;
    window.restoreHistoryEntry = restoreHistoryEntry;
    window.clearQueryHistory = clearQueryHistory;
    window.hydrateDataHistoryFromWorkspace = hydrateDataHistoryFromWorkspace;
    window.initEditor = initEditor;
    window.goToDataResultsPage = goToDataResultsPage;
    window.setDataResultsPageSize = setDataResultsPageSize;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
})();
