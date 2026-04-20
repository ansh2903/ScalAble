// ─── Notebook State ───────────────────────────────────────────
let notebookOpen = false;
let cellCounter = 0;
const cells = {}; // cellId → { code, outputEl, statusEl, countEl }

const MIME_RENDERERS = [
{
  mimeType: 'application/vnd.plotly.v1+json',
  priority: 100,
  render(data, container) {
    const wrapper = document.createElement('div');
    wrapper.className = 'p-3 border-t border-slate-100';
    const plotDiv = document.createElement('div');
    plotDiv.style.width = '100%';
    plotDiv.style.minHeight = '400px';
    wrapper.appendChild(plotDiv);
    container.appendChild(wrapper);

    // If Plotly isn't loaded yet, show a helpful message instead of crashing
    if (typeof Plotly === 'undefined') {
        plotDiv.innerHTML = `<p class="text-[10px] text-red-400 font-mono">Error: Plotly.js not found in frontend.</p>`;
        return;
    }

    // Logic: Notebooks sometimes send strings, sometimes objects. 
    // Handle both so the 'JSON.parse' doesn't kill the script.
    const spec = typeof data === 'string' ? JSON.parse(data) : data;

    Plotly.newPlot(plotDiv, spec.data, spec.layout ?? {}, {
      responsive: true,
      displayModeBar: true,
    });
  }
},    {
    mimeType: 'application/vnd.jupyter.widget-view+json',
    priority: 90,
    render(data, container) {
      // Stub — wire up ipywidgets here if needed
      const parsed = JSON.parse(data);
      container.insertAdjacentHTML('beforeend', `
        <pre class="font-mono text-[11px] p-3 text-amber-600 border-t border-slate-100">
          [Widget: ${parsed.model_id} — ipywidgets not yet connected]
        </pre>`);
    }
  },
  {
    mimeType: 'text/html',
    priority: 50,
    render(data, container) {
      container.insertAdjacentHTML('beforeend', `
        <div class="p-3 border-t border-slate-100 overflow-x-auto text-[11px]">
          ${data}
        </div>`);
    }
  },
  {
    mimeType: 'image/png',
    priority: 40,
    render(data, container) {
      container.insertAdjacentHTML('beforeend', `
        <div class="p-3 border-t border-slate-100">
          <img src="data:image/png;base64,${data}"
               class="max-w-full rounded-lg shadow-sm" />
        </div>`);
    }
  },
  {
    mimeType: 'image/svg+xml',
    priority: 45,
    render(data, container) {
      container.insertAdjacentHTML('beforeend', `
        <div class="p-3 border-t border-slate-100 overflow-x-auto">
          ${data}
        </div>`);
    }
  },
  {
    mimeType: 'text/plain',
    priority: 10, // lowest — fallback only
    render(data, container) {
      container.insertAdjacentHTML('beforeend', `
        <pre class="font-mono text-[11px] p-3 text-slate-600 border-t border-slate-100 whitespace-pre-wrap m-0">${data}</pre>`);
    }
  },
];

function addCell(initialCode = '') {
    cellCounter++;
    const cellId = `cell-${cellCounter}`;

    const cellHtml = `
    <div id="${cellId}" class="heavy-card p-3 bg-white border-slate-100">
        
        <!-- Cell Header -->
        <div class="flex justify-between mb-2">    
        <span id="${cellId}-count" class="text-[9px] font-black text-slate-400 uppercase tracking-widest bg-slate-50 px-2 py-0.5 rounded-pill border border-slate-100">
                In [ ] — Execution Block: Python
            </span>

            <span class="text-[9px] text-primary font-black uppercase tracking-wider">Completed in
                0.8s</span>

            <div class="flex items-center gap-1">
                <button onclick="runCell('${cellId}')"
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

        <!-- Code Input -->
<div class="bg-slate-50 border border-slate-100 p-2.5 rounded-lg">
<textarea 
    id="${cellId}-input"
    class="w-full bg-transparent border-none outline-none focus:outline-none focus:ring-0 p-0 m-0 resize-none overflow-hidden font-mono text-[11px] text-slate-700 leading-relaxed block"
    placeholder="# Write Python here..."
    onkeydown="handleCellKeydown(event, '${cellId}')"
    oninput="this.style.height = 'auto'; this.style.height = this.scrollHeight + 'px';"
    spellcheck="false"
    rows="1">${initialCode}</textarea>
    </div>    

    <!-- Will think about what can be done here later
        <div class="mt-2 p-2 bg-emerald-50/50 border border-primary/10 rounded-lg">
            <div class="flex items-center gap-2 mb-1">
                <span class="material-symbols-outlined text-primary text-sm">terminal</span>
                <p class="text-[9px] font-black text-primary uppercase tracking-widest">Analysis Output</p>
            </div>
            <p class="text-[10px] text-slate-600 font-medium leading-tight">
                Successfully computed retention rates for <span
                    class="font-bold text-slate-900">4,281</span> unique records. Detected a churn spike
                (-32%) in the <span class="font-bold text-slate-900">12-18 month</span> bracket.
            </p>
        </div>
-->
        <!-- Output Area -->
        <div id="${cellId}-output" class="hidden border-t border-slate-100">
            <!-- Output chunks rendered here -->
        </div>

    </div>`;

    document.getElementById('notebook-cells').insertAdjacentHTML('beforeend', cellHtml);

    // Register in state
    cells[cellId] = {
        executionCount: null,
        outputEl: document.getElementById(`${cellId}-output`),
        countEl: document.getElementById(`${cellId}-count`),
        inputEl: document.getElementById(`${cellId}-input`)
    };

    // Focus the new cell
    document.getElementById(`${cellId}-input`).focus();
    autoResizeCell(document.getElementById(`${cellId}-input`));
}

function deleteCell(cellId) {
    document.getElementById(cellId)?.remove();
    delete cells[cellId];
}

function autoResizeCell(textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = Math.max(80, textarea.scrollHeight) + 'px';
}

function handleCellKeydown(e, cellId) {
    if (e.key === 'Enter' && (e.ctrlKey || e.shiftKey)) {
        e.preventDefault();
        runCell(cellId);
    }

    // Tab → indent
    if (e.key === 'Tab') {
        e.preventDefault();
        const ta = e.target;
        const start = ta.selectionStart;
        ta.value = ta.value.slice(0, start) + '    ' + ta.value.slice(ta.selectionEnd);
        ta.selectionStart = ta.selectionEnd = start + 4;
    }
}

function runCell(cellId) {
    const cell = cells[cellId];
    if (!cell) return;

    const code = cell.inputEl.value.trim();
    if (!code) return;

    // Clear previous output
    cell.outputEl.innerHTML = '';
    cell.outputEl.classList.remove('hidden');
    cell.countEl.textContent = 'In [*] — Running...';
    addCell();

    socket.emit('kernel_execute', { cell_id: cellId, code });
}

// ─── Handle incoming kernel output ───────────────────────────

// Pick the highest-priority renderer available in a data bundle
function renderMimeBundle(dataBundle, container) {
  const available = MIME_RENDERERS
    .filter(r => dataBundle[r.mimeType] !== undefined)
    .sort((a, b) => b.priority - a.priority);

  if (available.length === 0) return;
  available[0].render(dataBundle[available[0].mimeType], container);
}

// ── Main Output Handler ─────────────────────────────────────────────────────

function handleKernelOutput(chunk) {
  const cell = cells[chunk.cell_id];
  if (!cell) return;
  const out = cell.outputEl;

  if (chunk.type === 'stream') {
    let streamEl = out.querySelector(`.stream-output[data-stream="${chunk.stream}"]`);
    if (!streamEl) {
      out.insertAdjacentHTML('beforeend', `
        <pre class="stream-output font-mono text-[11px] p-3 leading-relaxed whitespace-pre-wrap m-0
             ${chunk.stream === 'stderr' ? 'text-amber-600 bg-amber-50' : 'text-slate-700'}"
             data-stream="${chunk.stream}"></pre>`);
      streamEl = out.querySelector(`.stream-output[data-stream="${chunk.stream}"]`);
    }
    // Use textContent += to avoid XSS from user output
    streamEl.textContent += chunk.content;
  }

  else if (chunk.type === 'display' || chunk.type === 'result') {
    renderMimeBundle(chunk.data, out); // ← registry does the rest

    if (chunk.type === 'result') {
      cell.countEl.textContent = `Out [${chunk.execution_count}]`;
    }
  }

  else if (chunk.type === 'error') {
    const clean = chunk.traceback
      .join('\n')
      .replace(/\x1b\[[0-9;]*m/g, '');
    out.insertAdjacentHTML('beforeend', `
      <pre class="font-mono text-[11px] p-3 text-red-500 bg-red-50 border-t border-red-100 whitespace-pre-wrap m-0">${clean}</pre>`);
    cell.countEl.textContent = `In [!] — Error`;
  }

  else if (chunk.type === 'done') {
    if (cell.countEl.textContent.includes('*')) {
      cell.countEl.textContent = `In [✓] — Complete`;
    }
  }
}

// Add first cell on load
addCell();

// ------------------------------------------------------------
// Kernel stuff

const socket = io();
let mySessionId = null;

socket.on('connect', () => {
    console.log('Kernel socket connected');
});

socket.on('kernel_status', (data) => {
    mySessionId = data.session_id;
    console.log('Kernel status:', data.status);
});

socket.on('kernel_output', (chunk) => {
    // Route output to the correct cell by cell_id
    handleKernelOutput(chunk);
});

function executeCell(cellId, code) {
    socket.emit('kernel_execute', { cell_id: cellId, code: code });
}

function interruptKernel() {
    socket.emit('kernel_interrupt');
}

function restartKernel(kernelName = 'python3') {
    socket.emit('kernel_restart', { kernel_name: kernelName });
}
