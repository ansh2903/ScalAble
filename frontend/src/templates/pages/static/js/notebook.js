let notebookOpen = false;
let cellCounter = 0;
const cells = {};
let activeCellId = null;
let isCommandMode = true;
let lastKeyPress = { key: null, time: 0 };
let _notebookHydrating = false;
let _notebookSaveTimer = null;
let _recentlyDeleted = null;
let _dragCellId = null;

function getOrderedCellIds() {
  const container = document.getElementById('notebook-cells');
  if (!container) return [];
  return Array.from(container.children).map((el) => el.id).filter((id) => cells[id]);
}

function ensureNotebookTheme(monaco) {
  if (!monaco || window.__sporeNotebookThemeReady) return;
  window.__sporeNotebookThemeReady = true;
  monaco.editor.defineTheme('spore-theme', {
    base: 'vs',
    inherit: true,
    rules: [
      { token: 'keyword', foreground: '00A36C', fontStyle: 'bold' },
      { token: 'string', foreground: '065f46', fontStyle: 'bold' },
      { token: 'comment', foreground: '64748b', fontStyle: 'italic' },
      { token: 'identifier', foreground: '334155' },
      { token: 'number', foreground: '0f172a', fontStyle: 'bold' },
    ],
    colors: {
      'editor.background': '#f8fafc',
      'editor.foreground': '#334155',
      'editor.lineHighlightBackground': '#f1f5f9',
      'editorLineNumber.foreground': '#94a3b8',
      'editorIndentGuide.background': '#e2e8f0',
      'editor.selectionBackground': '#bbf7d0',
    },
  });
}

function insertCellHtml(cellHtml, opts = {}) {
  const container = document.getElementById('notebook-cells');
  if (!container) return;
  if (opts.insertBefore) {
    const ref = document.getElementById(opts.insertBefore);
    if (ref) ref.insertAdjacentHTML('beforebegin', cellHtml);
    else container.insertAdjacentHTML('beforeend', cellHtml);
  } else if (opts.insertAfter) {
    const ref = document.getElementById(opts.insertAfter);
    if (ref) ref.insertAdjacentHTML('afterend', cellHtml);
    else container.insertAdjacentHTML('beforeend', cellHtml);
  } else {
    container.insertAdjacentHTML('beforeend', cellHtml);
  }
}

function resolveCellIdForEditor(editor) {
  if (!editor) return activeCellId;
  const node = editor.getContainerDomNode?.();
  if (node?.id?.endsWith('-editor')) {
    const id = node.id.slice(0, -'-editor'.length);
    if (cells[id]) return id;
  }
  for (const id of getOrderedCellIds()) {
    if (cells[id]?.editor === editor) return id;
  }
  return activeCellId;
}

function executeNotebookRun(editor, advance) {
  const cellId = resolveCellIdForEditor(editor);
  if (!cellId || !cells[cellId]) return;
  const cell = cells[cellId];
  if (cell.type === 'sql') runSqlCell(cellId, advance);
  else if (cell.type === 'markdown') renderMarkdownCell(cellId, advance);
  else runCell(cellId, advance);
}

function focusCellEditor(cellId) {
  const cell = cells[cellId];
  if (!cell) return;

  activeCellId = cellId;

  if (cell.type === 'markdown' && cell.markdownRendered) {
    isCommandMode = true;
    highlightActiveCell();
    document.getElementById(cellId)?.focus();
    return;
  }

  if (cell.editor) {
    isCommandMode = false;
    cell.editor.focus();
    highlightActiveCell();
    return;
  }

  let attempts = 0;
  const tryFocus = () => {
    if (!cells[cellId]) return;
    if (cells[cellId].editor) {
      focusCellEditor(cellId);
      return;
    }
    if (++attempts < 40) setTimeout(tryFocus, 50);
  };
  setTimeout(tryFocus, 0);
}

function focusOrCreateBelow(cellId) {
  const ids = getOrderedCellIds();
  let idx = ids.indexOf(cellId);
  if (idx < 0 && activeCellId && cells[activeCellId]) {
    cellId = activeCellId;
    idx = ids.indexOf(cellId);
  }
  if (idx < 0) return;

  const nextId = ids[idx + 1];
  if (nextId) {
    focusCellEditor(nextId);
  } else {
    addCell('python', '', { userInitiated: true, insertAfter: cellId });
  }
}

function cellDragHandleHtml(cellId) {
  return `<span class="cell-drag-handle cursor-grab active:cursor-grabbing text-slate-300 hover:text-primary material-symbols-outlined text-[14px] select-none" draggable="true" data-cell-id="${cellId}" title="Drag to reorder">drag_indicator</span>`;
}

const SPORE_CONNECTIONS = window.SPORE_CONNECTIONS || [];
const socket = window.sporeSocket || (window.sporeSocket = io());

const KERNEL_STATUS_CONFIG = {
  connecting:   { label: 'Connecting',   dot: 'bg-amber-400 animate-pulse', text: 'text-amber-600' },
  idle:         { label: 'Idle',         dot: 'bg-primary',                 text: 'text-primary-dark' },
  busy:         { label: 'Busy',         dot: 'bg-amber-500 animate-pulse',  text: 'text-amber-600' },
  restarting:   { label: 'Restarting',   dot: 'bg-amber-500 animate-pulse', text: 'text-amber-600' },
  interrupted:  { label: 'Interrupted',  dot: 'bg-red-500',                 text: 'text-red-500' },
  disconnected: { label: 'Disconnected', dot: 'bg-slate-400',               text: 'text-slate-400' },
  error:        { label: 'Error',        dot: 'bg-red-500',                 text: 'text-red-500' },
};

function setKernelStatus(state) {
  const cfg = KERNEL_STATUS_CONFIG[state] || KERNEL_STATUS_CONFIG.disconnected;
  const dot = document.getElementById('kernel-status-dot');
  const text = document.getElementById('kernel-status-text');
  if (dot) dot.className = `w-1.5 h-1.5 rounded-pill ${cfg.dot}`;
  if (text) {
    text.textContent = cfg.label;
    text.className = `font-mono ${cfg.text}`;
  }
}

function stopRestartSpinner() {
  const icon = document.getElementById('restart-kernel-icon');
  if (icon) icon.classList.remove('animate-spin');
}

setKernelStatus('connecting');

socket.on('connect', () => {
  console.log('Kernel socket connected');
  setKernelStatus('idle');
});
socket.on('disconnect', () => {
  stopRestartSpinner();
  setKernelStatus('disconnected');
});
socket.on('kernel_status', (data) => {
  switch (data && data.status) {
    case 'connected':
    case 'restarted':
      stopRestartSpinner();
      setKernelStatus('idle');
      break;
    case 'interrupted':
      setKernelStatus('interrupted');
      setTimeout(() => setKernelStatus('idle'), 1200);
      break;
    case 'busy':
      setKernelStatus('busy');
      break;
    case 'idle':
      setKernelStatus('idle');
      break;
    default:
      if (data && data.status) setKernelStatus(data.status);
  }
});
socket.on('kernel_output', (chunk) => handleKernelOutput(chunk));

function interruptKernel() {
  socket.emit('kernel_interrupt');
  setKernelStatus('interrupted');
}

function restartKernel(kernelName = 'python3') {
  socket.emit('kernel_restart', { kernel_name: kernelName });
  setKernelStatus('restarting');
  const icon = document.getElementById('restart-kernel-icon');
  if (icon) icon.classList.add('animate-spin');
}

function normalizeCellType(type) {
  if (type === 'sql') return 'sql';
  if (type === 'markdown') return 'markdown';
  return 'python';
}

function getNotebookDisplayName() {
  const el = document.getElementById('notebook-header-name');
  const fromInput = (el?.value || '').trim();
  if (fromInput) return fromInput;
  return window.SPORE_WORKSPACE?.name || 'Untitled';
}

function serializeNotebookState() {
  const serialized = getOrderedCellIds().map((cellId) => {
    const cell = cells[cellId];
    return {
      id: cellId,
      type: normalizeCellType(cell.type),
      code: cell.editor ? cell.editor.getValue() : '',
      connectionId: cell.connEl ? cell.connEl.value : null,
      materialized: cell.materialized || null,
      streamName: cell.streamName || null,
      relationId: cell.relationId || null,
    };
  });
  return { name: getNotebookDisplayName(), cell_counter: cellCounter, cells: serialized };
}

function scheduleNotebookSave() {
  if (_notebookHydrating) return;
  clearTimeout(_notebookSaveTimer);
  _notebookSaveTimer = setTimeout(() => {
    if (typeof window.saveWorkspaceStatePatch === 'function') {
      window.saveWorkspaceStatePatch({ notebook: serializeNotebookState() });
    }
  }, 500);
}

function defaultNotebookCells() {
  window.monacoReady?.then((monaco) => {
    ensureNotebookTheme(monaco);
    monaco.editor.setTheme('spore-theme');
  });
  if (SPORE_CONNECTIONS.length) {
    addCell('python');
  } else {
    addCell('sql', 'SELECT 1 AS ok;');
  }
}

window.hydrateNotebookFromWorkspace = function hydrateNotebookFromWorkspace(notebook) {
  _notebookHydrating = true;
  try {
    const nameEl = document.getElementById('notebook-header-name');
    if (nameEl) {
      nameEl.value = notebook?.name || window.SPORE_WORKSPACE?.name || 'Untitled';
    }

    const saved = notebook && Array.isArray(notebook.cells) ? notebook.cells : [];
    if (!saved.length) {
      defaultNotebookCells();
      return;
    }

    const container = document.getElementById('notebook-cells');
    if (container) container.innerHTML = '';
    Object.keys(cells).forEach((k) => delete cells[k]);
    cellCounter = notebook.cell_counter || 0;

    window.monacoReady?.then((monaco) => {
      ensureNotebookTheme(monaco);
      monaco.editor.setTheme('spore-theme');
    });

    saved.forEach((c) => {
      const type = normalizeCellType(c.type);
      addCell(type, c.code || '', {
        connectionId: c.connectionId,
        materialized: c.materialized,
        streamName: c.streamName,
        relationId: c.relationId,
        savedCellId: c.id,
      });
    });
  } finally {
    _notebookHydrating = false;
    const ids = getOrderedCellIds();
    if (ids.length) {
      activeCellId = ids[0];
      isCommandMode = true;
      highlightActiveCell();
    }
  }
};

window.notebookOnLeaveView = function notebookOnLeaveView() {
  activeCellId = null;
  isCommandMode = false;
};

window.renameNotebook = function renameNotebook(name) {
  const trimmed = (name || '').trim();
  const finalName = trimmed || window.SPORE_WORKSPACE?.name || 'Untitled';
  const nameEl = document.getElementById('notebook-header-name');
  if (nameEl) nameEl.value = finalName;
  if (typeof window.saveWorkspaceStatePatch === 'function') {
    window.saveWorkspaceStatePatch({ notebook: { name: finalName } }, true);
  }
};

// Initial cells are created by workspace.js via hydrateNotebookFromWorkspace().


function connectionOptionsHtml(selectedId = '') {
  if (!SPORE_CONNECTIONS.length) {
    return '<option value="" disabled selected>No connections — add one first</option>';
  }
  return SPORE_CONNECTIONS.map(c => {
    const sel = String(c.id) === String(selectedId) ? 'selected' : '';
    const label = `${c.source_type || c.db_type || 'db'} — ${c.name || c.id}`;
    return `<option value="${c.id}" ${sel}>${label}</option>`;
  }).join('');
}

function addCell(type = 'python', initialCode = '', opts = {}) {
  // Use a secure UUID for newly generated entities, or fall back to an explicitly loaded ID
  const cellId = opts.savedCellId || `cell-${crypto.randomUUID()}`;

  const cellType = normalizeCellType(type);
  let cellHtml;
  if (cellType === 'sql') cellHtml = buildSqlCellHtml(cellId, initialCode, opts);
  else if (cellType === 'markdown') cellHtml = buildMarkdownCellHtml(cellId, initialCode, opts);
  else cellHtml = buildPythonCellHtml(cellId, initialCode, opts);

  insertCellHtml(cellHtml, opts);
  wireCellDnd(cellId);

  const isMarkdown = cellType === 'markdown';
  cells[cellId] = {
    type: cellType,
    outputEl: document.getElementById(`${cellId}-output`),
    countEl: document.getElementById(`${cellId}-count`),
    editEl: isMarkdown ? document.getElementById(`${cellId}-edit`) : null,
    renderEl: isMarkdown ? document.getElementById(`${cellId}-render`) : null,
    editor: null,
    connEl: cellType === 'sql' ? document.getElementById(`${cellId}-conn`) : null,
    statusEl: cellType === 'sql' ? document.getElementById(`${cellId}-status`) : null,
    materialized: opts.materialized || null,
    streamName: opts.streamName || null,
    relationId: opts.relationId || null,
    markdownRendered: isMarkdown && !!(initialCode || '').trim(),
    outputs: [],
  };

  if (isMarkdown && cells[cellId].renderEl) {
    cells[cellId].renderEl.addEventListener('dblclick', (e) => {
      e.preventDefault();
      enterMarkdownEdit(cellId);
    });
    if (cells[cellId].markdownRendered) {
      setMarkdownCellMode(cellId, 'rendered');
    } else {
      setMarkdownCellMode(cellId, 'edit');
    }
  }

  window.monacoReady.then((monaco) => {
    mountMonacoEditor(monaco, cellId, cellType, initialCode, opts);
  });

  if (opts.activateCommandMode) {
    activeCellId = cellId;
    isCommandMode = true;
    highlightActiveCell();
    document.getElementById(cellId)?.setAttribute('tabindex', '-1');
    document.getElementById(cellId)?.focus();
  }

  return cellId;
}

function wireNotebookEditorRunKeys(monaco, editor) {
  editor.onKeyDown((e) => {
    if (e.keyCode !== monaco.KeyCode.Enter) return;

    let advance;
    if (e.shiftKey && !e.altKey && !(e.ctrlKey || e.metaKey)) {
      advance = true;
    } else if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey) {
      advance = false;
    } else if (e.altKey && !e.shiftKey) {
      advance = 'always';
    } else {
      return;
    }

    e.preventDefault();
    e.stopPropagation();
    executeNotebookRun(editor, advance);
  });
}

function mountMonacoEditor(monaco, cellId, cellType, initialCode, opts) {
  setupMonacoPython(monaco);
  ensureNotebookTheme(monaco);

  const editorContainer = document.getElementById(`${cellId}-editor`);
  if (!editorContainer) return;

  const existing = cells[cellId]?.editor;
  if (existing?.dispose) {
    try { existing.dispose(); } catch (_) { /* noop */ }
    cells[cellId].editor = null;
  }

  const lang = cellType === 'sql' ? 'sql' : cellType === 'markdown' ? 'markdown' : 'python';
  let value = initialCode;
  if (cellType === 'python' && opts.requireMaterialized && !opts.materialized) {
    value = '# Materialize a SQL cell first...';
  }

  editorContainer.style.minHeight = '40px';

  const editor = monaco.editor.create(editorContainer, {
    value,
    language: lang,
    theme: 'spore-theme',
    minimap: { enabled: false },
    scrollBeyondLastLine: false,
    automaticLayout: true,
    fontSize: 12,
    fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
    lineNumbers: 'off',
    renderLineHighlight: 'all',
    wordWrap: 'on',
    padding: { top: 12, bottom: 12 },
    overviewRulerLanes: 0,
    hideCursorInOverviewRuler: true,
    scrollbar: {
      vertical: 'hidden',
      alwaysConsumeMouseWheel: false,
    },
  });

  editor.onDidContentSizeChange((e) => {
    if (e.contentHeightChanged) {
      editorContainer.style.height = `${e.contentHeight}px`;
      editor.layout();
    }
  });

  setTimeout(() => {
    editorContainer.style.height = `${editor.getContentHeight()}px`;
    editor.layout();
  }, 0);

  cells[cellId].editor = editor;
  editor.onDidChangeModelContent(() => scheduleNotebookSave());

  wireNotebookEditorRunKeys(monaco, editor);

  editor.addCommand(monaco.KeyCode.Escape, () => {
    const id = resolveCellIdForEditor(editor);
    document.activeElement?.blur();
    isCommandMode = true;
    activeCellId = id;
    highlightActiveCell();
    document.getElementById(id)?.focus();
  });

  editor.onDidFocusEditorText(() => {
    monaco.editor.setTheme('spore-theme');
    activeCellId = resolveCellIdForEditor(editor);
    isCommandMode = false;
    highlightActiveCell();
  });

  if (opts.userInitiated && !_notebookHydrating) {
    if (cellType === 'markdown') enterMarkdownEdit(cellId);
    else editor.focus();
  }

  if (cellType === 'markdown' && !_notebookHydrating) {
    if (cells[cellId].markdownRendered) {
      updateMarkdownRender(cellId);
      setMarkdownCellMode(cellId, 'rendered');
    } else {
      setMarkdownCellMode(cellId, 'edit');
    }
  }

  scheduleNotebookSave();
}

function wireCellDnd(cellId) {
  const wrapper = document.getElementById(cellId);
  const handle = wrapper?.querySelector('.cell-drag-handle');
  if (!wrapper || !handle) return;

  handle.addEventListener('dragstart', (e) => {
    _dragCellId = cellId;
    wrapper.classList.add('opacity-60');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', cellId);
  });

  handle.addEventListener('dragend', () => {
    wrapper.classList.remove('opacity-60');
    document.querySelectorAll('.cell-drop-before, .cell-drop-after').forEach((el) => {
      el.classList.remove('cell-drop-before', 'cell-drop-after');
    });
    _dragCellId = null;
  });

  const clearDropIndicator = () => {
    wrapper.style.borderTop = '';
    wrapper.style.borderBottom = '';
  };

  wrapper.addEventListener('dragover', (e) => {
    if (!_dragCellId || _dragCellId === cellId) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    const rect = wrapper.getBoundingClientRect();
    const before = e.clientY < rect.top + rect.height / 2;
    clearDropIndicator();
    if (before) wrapper.style.borderTop = '3px solid #00A36C';
    else wrapper.style.borderBottom = '3px solid #00A36C';
  });

  wrapper.addEventListener('dragleave', (e) => {
    if (!wrapper.contains(e.relatedTarget)) clearDropIndicator();
  });

  wrapper.addEventListener('drop', (e) => {
    e.preventDefault();
    const sourceId = _dragCellId || e.dataTransfer.getData('text/plain');
    clearDropIndicator();
    if (!sourceId || sourceId === cellId) return;

    const sourceNode = document.getElementById(sourceId);
    if (!sourceNode) return;

    const rect = wrapper.getBoundingClientRect();
    const before = e.clientY < rect.top + rect.height / 2;

    if (before) wrapper.parentNode.insertBefore(sourceNode, wrapper);
    else wrapper.parentNode.insertBefore(sourceNode, wrapper.nextSibling);

    scheduleNotebookSave();
    highlightActiveCell();
  });
}

function buildPythonCellHtml(cellId, initialCode, opts) {
  const blocked = opts.requireMaterialized && !opts.materialized;
  const code = blocked
    ? '# Materialize a SQL cell first, then add a Python cell from it.'
    : (initialCode || '');

  return `
    <div id="${cellId}" class="heavy-card p-3 bg-white border-slate-100 notebook-cell" data-cell-type="python" tabindex="-1">
        <div class="flex justify-between mb-2 items-center gap-2">
            ${cellDragHandleHtml(cellId)}
            <span id="${cellId}-count" class="text-[9px] font-black text-slate-400 uppercase tracking-widest bg-slate-50 px-2 py-0.5 rounded-pill border border-slate-100">
                In [ ] — Python (local)
            </span>
            <div class="flex items-center gap-1 ml-auto">
                <button onclick="runCell('${cellId}', false)"
                    class="flex items-center gap-1 px-2 py-1 bg-primary text-white text-[9px] font-black rounded hover:opacity-90 transition-all">
                    <span class="material-symbols-outlined text-[11px]" style="font-variation-settings:'FILL' 1">play_arrow</span>
                    RUN
                </button>
                <button onclick="deleteCell('${cellId}')"
                    class="p-1 text-slate-300 hover:text-red-400 transition-colors rounded">
                    <span class="material-symbols-outlined text-[13px]">delete</span>
                </button>
            </div>
        </div>
        <div class="bg-slate-50 border border-slate-100 p-2 rounded-lg">
            <div id="${cellId}-editor" class="w-full min-h-[60px]"></div>
        </div>
        <div id="${cellId}-output" class="hidden border-t border-slate-100 mt-2"></div>
    </div>`;
}

const MARKDOWN_EDIT_WRAPPER =
  'heavy-card p-3 bg-white border-slate-100 border-l-4 border-l-violet-300 notebook-cell markdown-cell';
const MARKDOWN_RENDER_WRAPPER =
  'notebook-cell markdown-cell px-2 py-3 border-l-4 border-l-transparent hover:border-l-violet-200/70 transition-colors';

function buildMarkdownCellHtml(cellId, initialCode, opts) {
  const hasContent = !!(initialCode || '').trim();
  const startRendered = hasContent;
  const placeholder = '<em class="text-slate-300 not-italic">Double-click to edit…</em>';
  const initialRender = hasContent && typeof marked !== 'undefined'
    ? marked.parse(initialCode)
    : placeholder;
  const wrapperClass = startRendered ? MARKDOWN_RENDER_WRAPPER : MARKDOWN_EDIT_WRAPPER;

  return `
    <div id="${cellId}" class="${wrapperClass}" data-cell-type="markdown" data-markdown-mode="${startRendered ? 'rendered' : 'edit'}" tabindex="-1">
        <div id="${cellId}-edit" class="${startRendered ? 'hidden' : ''}">
            <div class="flex justify-between mb-2 items-center gap-2">
                ${cellDragHandleHtml(cellId)}
                <span id="${cellId}-count" class="text-[9px] font-black text-slate-500 uppercase tracking-widest bg-slate-50 px-2 py-0.5 rounded-pill border border-slate-100">
                    Markdown
                </span>
                <div class="flex items-center gap-1 ml-auto">
                    <button onclick="renderMarkdownCell('${cellId}', false)"
                        class="flex items-center gap-1 px-2 py-1 bg-violet-50 text-violet-700 text-[9px] font-black rounded hover:opacity-90 transition-all">
                        <span class="material-symbols-outlined text-[11px]">visibility</span>
                        RENDER
                    </button>
                    <button onclick="deleteCell('${cellId}')"
                        class="p-1 text-slate-300 hover:text-red-400 transition-colors rounded">
                        <span class="material-symbols-outlined text-[13px]">delete</span>
                    </button>
                </div>
            </div>
            <div class="bg-slate-50 border border-slate-100 p-3 rounded-lg">
                <div id="${cellId}-editor" class="w-full min-h-[60px]"></div>
            </div>
        </div>
        <div id="${cellId}-render" title="Double-click to edit"
            class="markdown-rendered prose prose-slate max-w-none text-sm cursor-text min-h-[24px] px-1 ${startRendered ? '' : 'hidden'}">${initialRender}</div>
        <div id="${cellId}-output" class="hidden"></div>
    </div>`;
}

function setMarkdownCellMode(cellId, mode) {
  const cell = cells[cellId];
  const wrapper = document.getElementById(cellId);
  const editEl = document.getElementById(`${cellId}-edit`);
  const renderEl = cell?.renderEl;
  if (!cell || cell.type !== 'markdown' || !wrapper || !editEl || !renderEl) return;

  const rendered = mode === 'rendered';
  cell.markdownRendered = rendered;

  if (rendered) {
    editEl.classList.add('hidden');
    renderEl.classList.remove('hidden');
    wrapper.className = MARKDOWN_RENDER_WRAPPER;
    wrapper.dataset.markdownMode = 'rendered';
  } else {
    editEl.classList.remove('hidden');
    renderEl.classList.add('hidden');
    wrapper.className = MARKDOWN_EDIT_WRAPPER;
    wrapper.dataset.markdownMode = 'edit';
  }
}

function updateMarkdownRender(cellId) {
  const cell = cells[cellId];
  if (!cell?.renderEl) return;

  const raw = cell.editor ? (cell.editor.getValue() || '').trim() : '';
  if (!raw) {
    cell.renderEl.innerHTML = '<em class="text-slate-300 not-italic">Double-click to edit…</em>';
    return;
  }
  if (typeof marked !== 'undefined') {
    cell.renderEl.innerHTML = marked.parse(raw);
  } else {
    cell.renderEl.textContent = raw;
  }
  if (window.MathJax?.typesetPromise) {
    window.MathJax.typesetPromise([cell.renderEl]).catch(() => {});
  }
}

function enterMarkdownEdit(cellId) {
  const cell = cells[cellId];
  if (!cell || cell.type !== 'markdown') return;

  setMarkdownCellMode(cellId, 'edit');

  window.monacoReady.then((monaco) => {
    monaco.editor.setTheme('spore-theme');
    cell.editor?.layout();
    cell.editor?.focus();
  });
  activeCellId = cellId;
  isCommandMode = false;
  highlightActiveCell();
}

function renderMarkdownCell(cellId, advance = false) {
  const cell = cells[cellId];
  if (!cell || cell.type !== 'markdown') return;
  if (!cell.editor) return;

  updateMarkdownRender(cellId);
  setMarkdownCellMode(cellId, 'rendered');
  scheduleNotebookSave();

  if (advance === 'always') {
    addCell('python', '', { insertAfter: cellId, userInitiated: true });
  } else if (advance) {
    focusOrCreateBelow(cellId);
  } else {
    document.activeElement?.blur();
    isCommandMode = true;
    activeCellId = cellId;
    highlightActiveCell();
    document.getElementById(cellId)?.focus();
  }
}

function convertCell(cellId, newType) {
  const cell = cells[cellId];
  if (!cell) return;

  const code = cell.editor ? cell.editor.getValue() : '';
  const meta = {
    connectionId: cell.connEl?.value,
    materialized: cell.materialized,
    streamName: cell.streamName,
    relationId: cell.relationId,
    savedCellId: cellId,
    activateCommandMode: true,
  };

  const ids = getOrderedCellIds();
  const idx = ids.indexOf(cellId);
  const prevId = idx > 0 ? ids[idx - 1] : null;
  const nextId = ids[idx + 1] || null;

  deleteCell(cellId, { skipUndo: true });

  if (prevId) addCell(newType, code, { ...meta, insertAfter: prevId });
  else if (nextId) addCell(newType, code, { ...meta, insertBefore: nextId });
  else addCell(newType, code, meta);

  activeCellId = cellId;
  isCommandMode = true;
  highlightActiveCell();
  document.getElementById(cellId)?.focus();
}

function buildSqlCellHtml(cellId, opts) {
  const connId = opts.connectionId || (SPORE_CONNECTIONS[0] && SPORE_CONNECTIONS[0].id) || '';
  return `
    <div id="${cellId}" class="heavy-card p-3 bg-white border-slate-100 border-l-4 border-l-primary notebook-cell" data-cell-type="sql" tabindex="-1">
        <div class="flex justify-between mb-2 flex-wrap gap-2 items-center">
            ${cellDragHandleHtml(cellId)}
            <span id="${cellId}-count" class="text-[9px] font-black text-primary uppercase tracking-widest bg-primary-soft px-2 py-0.5 rounded-pill border border-primary/20">
                SQL — Remote pushdown
            </span>
            <select id="${cellId}-conn" class="text-[9px] font-black text-slate-600 bg-slate-50 border border-slate-200 rounded px-2 py-0.5 uppercase">
                ${connectionOptionsHtml(connId)}
            </select>
            <div class="flex items-center gap-1 ml-auto">
                <button onclick="askSqlCell('${cellId}')"
                    class="flex items-center gap-1 px-2 py-1 bg-slate-800 text-white text-[9px] font-black rounded hover:opacity-90">
                    <span class="material-symbols-outlined text-[11px]">auto_awesome</span> ASK AI
                </button>
                <button onclick="runSqlCell('${cellId}', false)"
                    class="flex items-center gap-1 px-2 py-1 bg-primary text-white text-[9px] font-black rounded hover:opacity-90">
                    <span class="material-symbols-outlined text-[11px]">play_arrow</span> RUN
                </button>
                <button onclick="materializeSqlCell('${cellId}')"
                    class="flex items-center gap-1 px-2 py-1 bg-emerald-600 text-white text-[9px] font-black rounded hover:opacity-90">
                    <span class="material-symbols-outlined text-[11px]">save</span> MATERIALIZE
                </button>
                <button onclick="deleteCell('${cellId}')"
                    class="p-1 text-slate-300 hover:text-red-400 transition-colors rounded">
                    <span class="material-symbols-outlined text-[13px]">delete</span>
                </button>
            </div>
        </div>
        <span id="${cellId}-status" class="text-[9px] text-slate-400 font-bold block mb-1">Preview on remote source</span>
<div class="bg-slate-50 border border-slate-100 p-2 rounded-lg">
    <div id="${cellId}-editor" class="w-full min-h-[80px]"></div>
</div>
        <div id="${cellId}-output" class="mt-2"></div>
    </div>`;
}

function deleteCell(cellId, opts = {}) {
  const cell = cells[cellId];
  if (!cell) return;

  if (cell.editor?.dispose) {
    try { cell.editor.dispose(); } catch (_) { /* noop */ }
  }

  if (!opts.skipUndo) {
    const ids = getOrderedCellIds();
    const idx = ids.indexOf(cellId);
    _recentlyDeleted = {
      type: cell.type,
      code: cell.editor ? cell.editor.getValue() : '',
      connectionId: cell.connEl?.value,
      materialized: cell.materialized,
      streamName: cell.streamName,
      relationId: cell.relationId,
      insertAfter: idx > 0 ? ids[idx - 1] : null,
      insertBefore: idx === 0 && ids.length > 1 ? ids[1] : null,
    };
  }

  document.getElementById(cellId)?.remove();
  delete cells[cellId];
  scheduleNotebookSave();
}

function undoDeleteCell() {
  if (!_recentlyDeleted) return;
  const d = _recentlyDeleted;
  _recentlyDeleted = null;
  const opts = {
    connectionId: d.connectionId,
    materialized: d.materialized,
    streamName: d.streamName,
    relationId: d.relationId,
    activateCommandMode: true,
  };
  if (d.insertAfter) addCell(d.type, d.code, { ...opts, insertAfter: d.insertAfter });
  else if (d.insertBefore) addCell(d.type, d.code, { ...opts, insertBefore: d.insertBefore });
  else addCell(d.type, d.code, opts);
}

function runCell(cellId, advance = false) {
  const cell = cells[cellId];
  if (!cell || cell.type !== 'python' || !cell.editor) return;

  const code = cell.editor.getValue().trim();
  if (!code) {
    if (advance) focusOrCreateBelow(cellId);
    return;
  }

  if (code.includes('Materialize a SQL cell first')) {
    alert('Materialize a SQL query first, then add a Python cell from the SQL cell.');
    return;
  }

  cell.outputEl.innerHTML = '';
  cell.outputs = [];
  cell.outputEl.classList.remove('hidden');
  cell.countEl.textContent = 'In [*] — Running...';
  setKernelStatus('busy');

  socket.emit('kernel_execute', { cell_id: cellId, code });

  if (advance === 'always') {
    addCell('python', '', { insertAfter: cellId, userInitiated: true });
  } else if (advance) {
    focusOrCreateBelow(cellId);
  }
}

async function runSqlCell(cellId, advance = false) {
  const cell = cells[cellId];
  if (!cell || cell.type !== 'sql' || !cell.editor) return;

  const sql = cell.editor.getValue().trim();
  const dbId = cell.connEl?.value;
  if (!sql || !dbId) {
    if (advance) focusOrCreateBelow(cellId);
    return;
  }

  cell.statusEl.textContent = 'Running preview on remote...';
  cell.outputs = [];
  cell.outputEl.innerHTML = buildSqlResultShell(cellId);

  const thead = document.getElementById(`thead-${cellId}`);
  const tbody = document.getElementById(`tbody-${cellId}`);
  const rowcount = document.getElementById(`rowcount-${cellId}`);

  const formData = new FormData();
  formData.append('query', sql);
  formData.append('id', dbId);

  try {
    const response = await fetch('/query-preview', { method: 'POST', body: formData });
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let totalRows = 0;
    let dbTotalRows = null;
    const PREVIEW_LIMIT = 100;

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const data = JSON.parse(line.slice(6));

        if (data.type === 'columns') {
          thead.innerHTML = `<tr>${data.content.map(col =>
            `<th class="px-3 py-2 text-left text-[9px] font-black uppercase text-slate-500 whitespace-nowrap">${col}</th>`
          ).join('')}</tr>`;
        }
        if (data.type === 'metadata') {
          dbTotalRows = data.total_rows;
        }
        if (data.type === 'rows') {
          const prev = totalRows;
          totalRows += data.content.length;
          let label = `Showing ${Math.min(totalRows, PREVIEW_LIMIT)}`;
          if (dbTotalRows !== null && dbTotalRows !== 'unknown') {
            label = `Total: ${Number(dbTotalRows).toLocaleString()} | ${label}`;
          }
          rowcount.textContent = label;

          if (prev < PREVIEW_LIMIT) {
            const slice = data.content.slice(0, PREVIEW_LIMIT - prev);
            tbody.insertAdjacentHTML('beforeend', slice.map((row, i) => `
              <tr class="${(prev + i) % 2 === 0 ? 'bg-white' : 'bg-slate-50/50'}">
                ${Object.values(row).map(val =>
              `<td class="px-3 py-1.5 text-[11px] border-b border-slate-100 whitespace-nowrap">${val === null ? '<span class="text-slate-300 italic">null</span>' : val}</td>`
            ).join('')}
              </tr>`).join(''));
          }
        }
        if (data.type === 'error') {
          tbody.innerHTML = `<tr><td colspan="99" class="px-3 py-3 text-red-500 font-bold">${data.content}</td></tr>`;
        }
      }
    }
    cell.statusEl.textContent = 'Preview (remote) — materialize to use in Python';
    if (cell.outputEl?.innerHTML?.trim()) {
      cell.outputs = [{ type: 'html_snapshot', content: cell.outputEl.innerHTML }];
    }
    if (advance === 'always') {
      addCell('python', '', { insertAfter: cellId, userInitiated: true });
    } else if (advance) {
      focusOrCreateBelow(cellId);
    }
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="99" class="px-3 py-3 text-red-500 font-bold">Connection lost.</td></tr>`;
    cell.statusEl.textContent = 'Preview failed';
  }
}

function buildSqlResultShell(cellId) {
  return `
    <div class="rounded-xl border border-slate-200 overflow-hidden bg-white">
      <div class="flex items-center gap-2 px-3 py-2 bg-slate-50 border-b border-slate-100">
        <span class="material-symbols-outlined text-[13px] text-primary">table</span>
        <span class="text-[9px] font-black uppercase text-slate-500">Query preview</span>
        <span id="rowcount-${cellId}" class="ml-auto text-[9px] font-black text-slate-400"></span>
      </div>
      <div class="overflow-x-auto max-h-64 overflow-y-auto">
        <table class="w-full text-[11px]">
          <thead id="thead-${cellId}" class="sticky top-0 bg-slate-50 border-b"></thead>
          <tbody id="tbody-${cellId}"></tbody>
        </table>
      </div>
    </div>`;
}

async function askSqlCell(cellId) {
  const cell = cells[cellId];
  if (!cell) return;
  const prompt = window.prompt('Ask AI to write or refine SQL:', '');
  if (!prompt) return;

  const dbId = cell.connEl?.value;
  if (!dbId) return;

  cell.statusEl.textContent = 'AI generating SQL...';

  const formData = new FormData();
  formData.append('message', prompt);
  formData.append('selected_db_id', dbId);
  formData.append('context_sql', cell.editor.getValue());

  try {
    const response = await fetch('/chat/ask', { method: 'POST', body: formData });
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let full = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value);
      for (const line of chunk.split('\n')) {
        if (!line.startsWith('data: ')) continue;
        const data = JSON.parse(line.slice(6));
        if (data.type === 'token') full += data.content;
      }
    }

    const match = full.match(/<query>([\s\S]*?)<\/query>/);
    if (match && match[1].trim()) {
      cell.editor.setValue(match[1].trim());
      cell.statusEl.textContent = 'SQL updated — run preview or materialize';
      scheduleNotebookSave();
    } else {
      cell.statusEl.textContent = 'AI did not return SQL';
    }
  } catch (e) {
    cell.statusEl.textContent = 'AI request failed';
  }
}

function sporeExtensionFromPath(path) {
  const m = String(path || '').match(/\.([a-z0-9]+)$/i);
  return m ? m[1].toLowerCase() : 'parquet';
}

function sporePandasReadExpr(path, format) {
  const ext = String(format || sporeExtensionFromPath(path) || 'parquet').toLowerCase();
  const escaped = String(path).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
  const readers = {
    parquet: `pd.read_parquet("${escaped}")`,
    csv: `pd.read_csv("${escaped}")`,
    tsv: `pd.read_csv("${escaped}", sep="\\t")`,
    json: `pd.read_json("${escaped}")`,
    xlsx: `pd.read_excel("${escaped}")`,
    xls: `pd.read_excel("${escaped}")`,
  };
  return readers[ext] || readers.parquet;
}

function addPythonFromMaterialized(kernelPath, streamName, relationId, format) {
  const readExpr = sporePandasReadExpr(kernelPath, format);
  const code = `import pandas as pd\ndf = ${readExpr}\ndf.head()`;
  if (typeof addCell === 'function') {
    addCell('python', code, {
      materialized: kernelPath,
      streamName: streamName || undefined,
      relationId: relationId || undefined,
    });
  }
}

window.sporePandasReadExpr = sporePandasReadExpr;
window.addPythonFromMaterialized = addPythonFromMaterialized;
window.sporeAddNotebookCell = function sporeAddNotebookCell(type, code) {
  return addCell(type || 'python', code || '', { activateCommandMode: false });
};

async function materializeSqlCell(cellId) {
  const cell = cells[cellId];
  if (!cell) return;

  const sql = cell.editor.getValue().trim();
  const dbId = cell.connEl?.value;
  if (!sql || !dbId) return;

  const streamName = cell.streamName || `stream_${cellId.replace('cell-', '')}`;
  cell.statusEl.textContent = 'Materializing to local volume...';

  const formData = new FormData();
  formData.append('query', sql);
  formData.append('id', dbId);
  formData.append('stream_name', streamName);
  if (cell.relationId) formData.append('relation_id', cell.relationId);

  try {
    const response = await fetch('/materialize', { method: 'POST', body: formData });
    const result = await response.json();

    if (result.status === 'success') {
      cell.materialized = result.kernel_path;
      cell.relationId = result.relation_id;
      cell.streamName = result.stream_name;
      cell.materializedFormat = result.format || sporeExtensionFromPath(result.kernel_path);
      const fmtArg = cell.materializedFormat ? `, '${cell.materializedFormat}'` : '';
      cell.statusEl.innerHTML = `<span class="text-emerald-600">Materialized</span> → <code class="text-[9px]">${result.kernel_path}</code>
        <button onclick="addPythonFromMaterialized('${result.kernel_path}', '${result.stream_name}', '${result.relation_id}'${fmtArg})"
          class="ml-2 px-2 py-0.5 bg-primary text-white text-[8px] font-black rounded">+ PYTHON CELL</button>`;
      scheduleNotebookSave();
    } else {
      cell.statusEl.textContent = `Materialize failed: ${result.message || 'unknown error'}`;
    }
  } catch (e) {
    cell.statusEl.textContent = 'Materialize failed';
  }
}

function renderMimeBundle(dataBundle, container) {
  if (typeof MIME_RENDERERS === 'undefined') return;
  const available = MIME_RENDERERS
    .filter(r => dataBundle[r.mimeType] !== undefined)
    .sort((a, b) => b.priority - a.priority);
  if (available.length === 0) return;
  available[0].render(dataBundle[available[0].mimeType], container);
}

function recordCellOutput(cell, chunk) {
  if (!cell || !chunk?.type) return;
  if (chunk.type === 'stream') {
    cell.outputs.push({ type: 'stream', stream: chunk.stream, content: chunk.content });
  } else if (chunk.type === 'display' || chunk.type === 'result') {
    cell.outputs.push({ type: chunk.type, data: chunk.data, execution_count: chunk.execution_count });
  } else if (chunk.type === 'error') {
    cell.outputs.push({
      type: 'error',
      ename: chunk.ename,
      evalue: chunk.evalue,
      traceback: chunk.traceback,
    });
  }
}

function handleKernelOutput(chunk) {
  const cell = cells[chunk.cell_id];
  if (!cell) return;
  const out = cell.outputEl;

  if (chunk.type === 'stream') {
    recordCellOutput(cell, chunk);
    let streamEl = out.querySelector(`.stream-output[data-stream="${chunk.stream}"]`);
    if (!streamEl) {
      out.insertAdjacentHTML('beforeend', `
        <pre class="stream-output font-mono text-[11px] p-3 leading-relaxed whitespace-pre-wrap m-0
             ${chunk.stream === 'stderr' ? 'text-amber-600 bg-amber-50' : 'text-slate-700'}"
             data-stream="${chunk.stream}"></pre>`);
      streamEl = out.querySelector(`.stream-output[data-stream="${chunk.stream}"]`);
    }
    streamEl.textContent += chunk.content;
  } else if (chunk.type === 'display' || chunk.type === 'result') {
    recordCellOutput(cell, chunk);
    renderMimeBundle(chunk.data, out);
    if (chunk.type === 'result') {
      cell.countEl.textContent = `Out [${chunk.execution_count}]`;
    }
  } else if (chunk.type === 'error') {
    recordCellOutput(cell, chunk);
    const clean = chunk.traceback.join('\n').replace(/\x1b\[[0-9;]*m/g, '');
    out.insertAdjacentHTML('beforeend', `
      <pre class="font-mono text-[11px] p-3 text-red-500 bg-red-50 border-t border-red-100 whitespace-pre-wrap m-0">${clean}</pre>`);
    cell.countEl.textContent = 'In [!] — Error';
    setKernelStatus('idle');
  } else if (chunk.type === 'done') {
    if (cell.countEl.textContent.includes('*')) {
      cell.countEl.textContent = 'In [✓] — Complete';
    }
    setKernelStatus('idle');
  }
}

function buildDataShell(componentId) {
  return `
    <div id="${componentId}-wrapper" class="my-3 rounded-xl border border-slate-200 shadow-sm overflow-hidden bg-white">
        <div class="flex items-center justify-between px-3 py-2 bg-slate-50 border-b border-slate-200">
            <div class="flex items-center gap-2">
                <span class="material-symbols-outlined text-[14px] text-primary">dataset</span>
                <span class="text-[10px] font-black uppercase tracking-wider text-slate-600">Local DataFrame</span>
            </div>
            <div class="flex items-center gap-3">
                <span id="${componentId}-rowcount" class="text-[10px] font-bold text-slate-400"></span>
                <div class="relative">
                    <span class="material-symbols-outlined absolute left-2 top-1/2 -translate-y-1/2 text-[12px] text-slate-400">search</span>
                    <input type="text" id="${componentId}-search" placeholder="Filter rows..." 
                           class="pl-6 pr-2 py-0.5 text-[10px] border border-slate-200 rounded-md bg-white focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary w-32 transition-all">
                </div>
            </div>
        </div>
        <div class="overflow-x-auto overflow-y-auto" style="max-height: 400px;">
            <table id="${componentId}-table" class="w-full text-left border-collapse">
                <thead id="${componentId}-thead" class="sticky top-0 bg-slate-100/95 backdrop-blur z-10 shadow-sm">
                </thead>
                <tbody id="${componentId}-tbody" class="divide-y divide-slate-100">
                </tbody>
            </table>
        </div>
    </div>`;
}

function initializeSmartTable(rawHtml, componentId) {
  // 1. Parse the ugly pandas HTML silently in memory
  const parser = new DOMParser();
  const doc = parser.parseFromString(rawHtml, 'text/html');
  const sourceTable = doc.querySelector('table');

  if (!sourceTable) {
    document.getElementById(`${componentId}-wrapper`).innerHTML = `<div class="p-3 text-red-500">Failed to parse table data.</div>`;
    return;
  }

  // 2. Extract Headers
  const thead = document.getElementById(`${componentId}-thead`);
  const sourceHeaders = Array.from(sourceTable.querySelectorAll('thead th'));

  let headerHtml = '<tr>';
  sourceHeaders.forEach((th, index) => {
    // Pandas usually leaves the top-left index header blank. Let's name it 'idx'
    const colName = th.innerText.trim() || (index === 0 ? 'idx' : `col_${index}`);
    headerHtml += `
            <th class="px-4 py-2 text-[10px] font-black text-slate-500 tracking-wider whitespace-nowrap border-b border-slate-200">
                ${colName}
            </th>`;
  });
  headerHtml += '</tr>';
  thead.innerHTML = headerHtml;

  // 3. Extract Rows
  const tbody = document.getElementById(`${componentId}-tbody`);
  const sourceRows = Array.from(sourceTable.querySelectorAll('tbody tr'));

  // Update Row Count
  document.getElementById(`${componentId}-rowcount`).innerText = `${sourceRows.length} rows`;

  let bodyHtml = '';
  sourceRows.forEach((tr, rowIndex) => {
    const cells = Array.from(tr.querySelectorAll('th, td'));

    bodyHtml += `<tr class="hover:bg-green-50/50 transition-colors group">`;
    cells.forEach((cell, cellIndex) => {
      const val = cell.innerText.trim();
      // Style numbers slightly differently for that Kaggle data-science feel
      const isNumber = !isNaN(val) && val !== '';
      const textClass = isNumber ? 'font-mono text-primary-600' : 'text-slate-700';
      const bgClass = (rowIndex % 2 === 0) ? 'bg-white' : 'bg-slate-50/30';

      bodyHtml += `
                <td class="px-4 py-1.5 text-[11px] whitespace-nowrap ${textClass} ${bgClass} group-hover:bg-transparent">
                    ${val === 'NaN' || val === 'None' ? '<span class="text-slate-300 italic">null</span>' : val}
                </td>`;
    });
    bodyHtml += `</tr>`;
  });

  tbody.innerHTML = bodyHtml;

  // 4. (Optional) Wire up the quick filter search bar
  const searchInput = document.getElementById(`${componentId}-search`);
  searchInput.addEventListener('input', (e) => {
    const term = e.target.value.toLowerCase();
    const rows = tbody.querySelectorAll('tr');
    rows.forEach(row => {
      const text = row.innerText.toLowerCase();
      row.style.display = text.includes(term) ? '' : 'none';
    });
  });
}

// Visual Feedback for Command Mode
function highlightActiveCell() {
  getOrderedCellIds().forEach((id) => {
    const el = document.getElementById(id);
    const cell = cells[id];
    if (!el || !cell) return;

    el.style.borderLeft = '4px solid transparent';
    el.style.outline = 'none';

    if (id === activeCellId) {
      el.style.borderLeft = isCommandMode ? '4px solid #94a3b8' : '4px solid #22c55e';
      el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  });
}

function handleDoubleKeyCommand(key, action) {
  const now = Date.now();
  if (lastKeyPress.key === key && now - lastKeyPress.time < 500) {
    lastKeyPress = { key: null, time: 0 };
    action();
    return true;
  }
  lastKeyPress = { key, time: now };
  return false;
}

function handleNotebookCommandKeydown(e) {
  const panel = document.getElementById('notebookPanel');
  if (!panel || panel.classList.contains('hidden')) return;
  if (!isCommandMode || !activeCellId) return;

  const cellIds = getOrderedCellIds();
  const currentIndex = cellIds.indexOf(activeCellId);
  const activeCell = cells[activeCellId];

  switch (e.key) {
    case 'ArrowUp':
      e.preventDefault();
      if (currentIndex > 0) {
        activeCellId = cellIds[currentIndex - 1];
        highlightActiveCell();
        document.getElementById(activeCellId)?.focus();
      }
      break;

    case 'ArrowDown':
      e.preventDefault();
      if (currentIndex < cellIds.length - 1) {
        activeCellId = cellIds[currentIndex + 1];
        highlightActiveCell();
        document.getElementById(activeCellId)?.focus();
      }
      break;

    case 'Enter':
      e.preventDefault();
      if (activeCell?.type === 'markdown') {
        enterMarkdownEdit(activeCellId);
      } else if (activeCell?.editor) {
        isCommandMode = false;
        window.monacoReady.then((monaco) => monaco.editor.setTheme('spore-theme'));
        activeCell.editor.focus();
      }
      break;

    case 'a':
    case 'A': {
      e.preventDefault();
      const idx = cellIds.indexOf(activeCellId);
      const newId = addCell('python', '', { insertBefore: activeCellId });
      const ids = getOrderedCellIds();
      activeCellId = ids[idx] || newId;
      isCommandMode = true;
      highlightActiveCell();
      document.getElementById(activeCellId)?.focus();
      break;
    }

    case 'b':
    case 'B': {
      e.preventDefault();
      const prevId = activeCellId;
      const newId = addCell('python', '', { insertAfter: prevId });
      const ids = getOrderedCellIds();
      const prevIdx = ids.indexOf(prevId);
      activeCellId = prevIdx >= 0 ? ids[prevIdx + 1] : newId;
      isCommandMode = true;
      highlightActiveCell();
      document.getElementById(activeCellId)?.focus();
      break;
    }

    case 'm':
    case 'M':
      e.preventDefault();
      convertCell(activeCellId, 'markdown');
      break;

    case 'y':
    case 'Y':
      e.preventDefault();
      convertCell(activeCellId, 'python');
      break;

    case 'z':
    case 'Z':
      e.preventDefault();
      undoDeleteCell();
      break;

    case 'i':
    case 'I':
      e.preventDefault();
      if (handleDoubleKeyCommand('i', () => interruptKernel())) {
        /* interrupted */
      }
      break;

    case '0':
      e.preventDefault();
      if (handleDoubleKeyCommand('0', () => restartKernel())) {
        /* restarted */
      }
      break;

    case 'd':
    case 'D': {
      e.preventDefault();
      if (handleDoubleKeyCommand('d', () => {
        deleteCell(activeCellId);
        const ids = getOrderedCellIds();
        if (ids.length === 0) {
          activeCellId = null;
        } else if (currentIndex > 0) {
          activeCellId = ids[Math.min(currentIndex - 1, ids.length - 1)];
        } else {
          activeCellId = ids[0];
        }
        highlightActiveCell();
        if (activeCellId) document.getElementById(activeCellId)?.focus();
      })) {
        /* deleted */
      }
      break;
    }

    default:
      break;
  }
}

// 3. Attach globally to the window object so keys are caught even if <body> is targeted
function initNotebookCommandMode() {
  if (window.__notebookCommandModeBound) return;
  window.__notebookCommandModeBound = true;
  window.addEventListener('keydown', handleNotebookCommandKeydown);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initNotebookCommandMode);
} else {
  initNotebookCommandMode();
}

function setupMonacoPython(monaco) {
  // Prevent registering multiple times if called again
  if (window.monacoPythonSetupDone) return;
  window.monacoPythonSetupDone = true;

  const pythonKeywords = [
    'False', 'None', 'True', 'and', 'as', 'assert', 'async', 'await',
    'break', 'class', 'continue', 'def', 'del', 'elif', 'else', 'except',
    'finally', 'for', 'from', 'global', 'if', 'import', 'in', 'is', 'lambda',
    'nonlocal', 'not', 'or', 'pass', 'raise', 'return', 'try', 'while', 'with', 'yield'
  ];

  const commonDataScienceLibs = [
    'pandas', 'numpy', 'matplotlib', 'matplotlib.pyplot', 'seaborn',
    'scipy', 'sklearn', 'tensorflow', 'torch', 'math', 'os', 'sys', 'json', 'datetime'
  ];

  const commonSnippets = [
    { label: 'pd', text: 'import pandas as pd' },
    { label: 'np', text: 'import numpy as np' },
    { label: 'plt', text: 'import matplotlib.pyplot as plt' }
  ];

  monaco.languages.registerCompletionItemProvider('python', {
    provideCompletionItems: function (model, position) {
      // Get the current word being typed
      const word = model.getWordUntilPosition(position);
      const range = {
        startLineNumber: position.lineNumber,
        endLineNumber: position.lineNumber,
        startColumn: word.startColumn,
        endColumn: word.endColumn
      };

      const suggestions = [];

      // 1. Add Keywords (import, as, def, etc.)
      pythonKeywords.forEach(kw => {
        suggestions.push({
          label: kw,
          kind: monaco.languages.CompletionItemKind.Keyword,
          insertText: kw,
          range: range
        });
      });

      // 2. Add Modules (pandas, numpy, etc.)
      commonDataScienceLibs.forEach(lib => {
        suggestions.push({
          label: lib,
          kind: monaco.languages.CompletionItemKind.Module,
          insertText: lib,
          range: range
        });
      });

      // 3. Add Magic Snippets
      commonSnippets.forEach(snip => {
        suggestions.push({
          label: snip.label,
          kind: monaco.languages.CompletionItemKind.Snippet,
          insertText: snip.text,
          documentation: `Standard import for ${snip.label}`,
          range: range
        });
      });

      return { suggestions: suggestions };
    }
  });
}

window.renderMarkdownCell = renderMarkdownCell;
window.enterMarkdownEdit = enterMarkdownEdit;
window.convertCell = convertCell;
window.undoDeleteCell = undoDeleteCell;

// ── Notebook export (.ipynb + HTML) ─────────────────────────────────────────

function sourceToLines(code) {
  const text = code == null ? '' : String(code);
  if (!text) return [];
  const lines = text.split('\n');
  if (text.endsWith('\n')) lines.push('');
  return lines;
}

function safeDownloadFilename(name, ext) {
  const base = (name || 'notebook').replace(/[^\w\-]+/g, '_').slice(0, 64) || 'notebook';
  return `${base}.${ext}`;
}

function buildIpynb() {
  const nbCells = getOrderedCellIds().map((cellId) => {
    const cell = cells[cellId];
    const code = cell.editor ? cell.editor.getValue() : '';
    if (cell.type === 'python') {
      return {
        cell_type: 'code',
        execution_count: null,
        metadata: {},
        outputs: [],
        source: sourceToLines(code),
      };
    }
    if (cell.type === 'markdown') {
      return {
        cell_type: 'markdown',
        metadata: {},
        source: sourceToLines(code),
      };
    }
    // SQL and other types -> markdown fenced sql block
    return {
      cell_type: 'markdown',
      metadata: { spore: { type: 'sql' } },
      source: sourceToLines(`\`\`\`sql\n${code}\n\`\`\``),
    };
  });

  return {
    nbformat: 4,
    nbformat_minor: 5,
    metadata: {
      kernelspec: {
        display_name: 'Python 3',
        language: 'python',
        name: 'python3',
      },
      language_info: {
        name: 'python',
        pygments_lexer: 'ipython3',
      },
    },
    cells: nbCells,
  };
}

function downloadIpynb() {
  const nb = buildIpynb();
  const name = safeDownloadFilename(getNotebookDisplayName(), 'ipynb');
  const blob = new Blob([JSON.stringify(nb, null, 1)], { type: 'application/x-ipynb+json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

function gatherCellsForHtmlExport() {
  return getOrderedCellIds().map((cellId) => {
    const cell = cells[cellId];
    return {
      type: cell.type,
      code: cell.editor ? cell.editor.getValue() : '',
      outputs: Array.isArray(cell.outputs) ? cell.outputs : [],
    };
  });
}

async function exportNotebookHtml() {
  const wsId = typeof window.getActiveWorkspaceId === 'function' ? window.getActiveWorkspaceId() : null;
  if (!wsId) {
    alert('No active workspace');
    return;
  }
  const payload = {
    name: getNotebookDisplayName(),
    cells: gatherCellsForHtmlExport(),
  };
  try {
    const res = await fetch(`/api/workspaces/${encodeURIComponent(wsId)}/notebook/export-html`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `Export failed (${res.status})`);
    }
    const blob = await res.blob();
    const name = safeDownloadFilename(payload.name, 'html');
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    console.warn('notebook HTML export failed', e);
    alert('Notebook HTML export failed: ' + (e.message || e));
  }
}

function toggleNotebookExportDropdown(force) {
  const menu = document.getElementById('notebook-export-dropdown');
  if (!menu) return;
  const open = force !== undefined ? force : menu.classList.contains('hidden');
  menu.classList.toggle('hidden', !open);
}

function initNotebookExportControls() {
  document.getElementById('notebook-export-toggle')?.addEventListener('click', (e) => {
    e.stopPropagation();
    toggleNotebookExportDropdown();
  });
  document.getElementById('export-notebook-ipynb')?.addEventListener('click', () => {
    toggleNotebookExportDropdown(false);
    downloadIpynb();
  });
  document.getElementById('export-notebook-html')?.addEventListener('click', () => {
    toggleNotebookExportDropdown(false);
    exportNotebookHtml();
  });
  document.addEventListener('click', (e) => {
    if (!e.target.closest('#notebook-export-menu')) toggleNotebookExportDropdown(false);
  });
}

window.buildIpynb = buildIpynb;
window.downloadIpynb = downloadIpynb;
window.exportNotebookHtml = exportNotebookHtml;
window.gatherCellsForHtmlExport = gatherCellsForHtmlExport;
window.serializeNotebookState = serializeNotebookState;
window.getNotebookDisplayName = getNotebookDisplayName;

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initNotebookExportControls);
} else {
  initNotebookExportControls();
}