// ─── Notebook State ───────────────────────────────────────────
let notebookOpen = false;
let cellCounter = 0;
const cells = {}; // cellId → { code, outputEl, statusEl, countEl }

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

// ------------------------------------------------------------

// Script for user text, file input handling and dynamic content updates
document.getElementById('hiddenFileInput').addEventListener('change', function (e) {
    const fileInfo = document.getElementById('fileInfo');
    const fileName = document.getElementById('fileName');

    if (this.files && this.files[0]) {
        fileName.textContent = this.files[0].name;
        fileInfo.classList.remove('hidden');
    }
});

function clearFile() {
    document.getElementById('hiddenFileInput').value = '';
    document.getElementById('fileInfo').classList.add('hidden');
}

// 1. Grab elements first
const messageInput = document.getElementById('messageInput');
const sendMessageBtn = document.getElementById('sendMessageBtn');
const chatContainer = document.getElementById('chat-messages-container');

// 2. The Keyboard & Auto-expand Logic
messageInput.addEventListener('input', function () {
    this.style.height = 'auto';
    this.style.height = (Math.min(this.scrollHeight, 150)) + 'px';
});

messageInput.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (this.value.trim() !== "") {
            sendMessageBtn.click();
        }
    }
});

// 3. The Send Handler
sendMessageBtn.addEventListener('click', async () => {
    const message = messageInput.value.trim();
    const dbId = document.getElementById('selected_db_id').value;

    if (!message || !dbId) return;

    switchToChatView();

    appendMessage('user', message);
    messageInput.value = '';

    const assistantMsgId = 'msg-' + Date.now();
    appendMessage('assistant', '', assistantMsgId); // Start empty
    const targetText = document.getElementById(`text-${assistantMsgId}`);

    const formData = new FormData();
    formData.append('message', message);
    formData.append('selected_db_id', dbId);

    try {
        const response = await fetch('/chat/ask', { method: 'POST', body: formData });
        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        let fullContent = "";

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value);
            const lines = chunk.split('\n');

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const data = JSON.parse(line.slice(6));

                    if (data.type === 'token') {
                        fullContent += data.content;
                        targetText.innerHTML = formatAIResponse(fullContent, dbId);
                        chatContainer.scrollTop = chatContainer.scrollHeight;
                    }

                    if (data.type === 'stats') {
                        console.log("Inference Stats:", data);
                    }
                }
            }
        }
    } catch (error) {
        targetText.innerText = "Kernel Panic: Connection Lost.";
    }
});

// This function creates the modal, asks for inputs, and calculates chunks dynamically
function triggerStreamConfig(base64Code, dbId, totalRows) {
    const modalId = `modal-${Date.now()}`;

    const modalHtml = `
    <div id="${modalId}" class="fixed inset-0 z-[100] flex items-center justify-center bg-slate-900/40 backdrop-blur-sm transition-opacity">
        <div class="bg-white rounded-xl shadow-2xl w-full max-w-sm overflow-hidden border border-slate-200">
            
            <div class="bg-slate-50 px-4 py-3 border-b border-slate-200">
                <h3 class="text-xs font-black uppercase tracking-widest text-slate-700 flex items-center gap-2">
                    <span class="material-symbols-outlined text-[16px] text-primary">terminal</span>
                    Initialize Notebook Stream
                </h3>
            </div>

            <div class="p-5 space-y-4">
                <div>
                    <label class="block text-[10px] font-black uppercase tracking-wider text-slate-500 mb-1.5">Notebook Variable Name</label>
                    <input type="text" id="stream-name-${modalId}" value="dataset_stream" autofocus
                        class="w-full text-xs font-mono px-3 py-2 border border-slate-200 rounded-md focus:ring-2 focus:ring-primary focus:border-primary outline-none text-slate-700">
                    <p class="mt-2 text-[9px] text-slate-400 italic">
                        Stream will respect the memory ceiling defined in your Global Settings.
                    </p>
                </div>
            </div>

            <div class="px-4 py-3 bg-slate-50 border-t border-slate-200 flex justify-end gap-2">
                <button onclick="document.getElementById('${modalId}').remove()" class="px-4 py-1.5 text-[10px] font-black tracking-wider text-slate-500 hover:bg-slate-200 rounded-md transition-colors">CANCEL</button>
                <button id="btn-confirm-${modalId}" class="px-4 py-1.5 text-[10px] font-black uppercase tracking-wider text-white bg-primary hover:bg-primary/90 rounded-md transition-colors shadow-sm">
                    START STREAM
                </button>
            </div>
        </div>
    </div>`;

    document.body.insertAdjacentHTML('beforeend', modalHtml);

    // Focus the input automatically
    document.getElementById(`stream-name-${modalId}`).select();

    document.getElementById(`btn-confirm-${modalId}`).addEventListener('click', () => {
        const streamName = document.getElementById(`stream-name-${modalId}`).value.trim() || 'dataset_stream';
        document.getElementById(modalId).remove();
        executeAnalysisStream(base64Code, dbId, totalRows, streamName);
    });
}

async function executeAnalysisStream(base64Code, dbId, totalRows, streamName) {
    const sql = decodeURIComponent(escape(atob(base64Code)));
    switchToSplitView();

    const formData = new FormData();
    formData.append('query', sql);
    formData.append('id', dbId);
    formData.append('stream_name', streamName); 

    try {
        const response = await fetch('/view-data-extraction', { method: 'POST', body: formData });
        const result = await response.json();
        
        if (result.status === 'success') {
            const pythonBoilerplate = `
print(f"stored '${streamName}' at (${result.path})")
`;

    addCell(pythonBoilerplate);

        } else {
            console.error("Backend failed to initialize stream:", result.message);
        }

    } catch (err) {
        console.error("Network error during stream initialization", err);
    }
}
// Add these empty functions to handle the button clicks
async function runQuery(base64Code, dbId, blockId) {
    if (!base64Code || !dbId) return;
    const sql = decodeURIComponent(escape(atob(base64Code)));

    // Find the query block and inject a results container after it
    const queryBlock = document.getElementById(blockId);
    if (!queryBlock) return;

    // Remove any previous result for this block
    const existingResult = document.getElementById(`result-${blockId}`);
    if (existingResult) existingResult.remove();

    // Insert a result container right after the query block
    // Insert a result container with the button in the top action bar
    queryBlock.insertAdjacentHTML('afterend', `
        <div id="result-${blockId}" class="mt-1 mb-3 rounded-xl border border-slate-200 overflow-hidden bg-white shadow-data-card">
            <div class="flex items-center gap-2 px-3 py-2 bg-slate-50 border-b border-slate-100">
                <span class="material-symbols-outlined text-[13px] text-primary">table</span>
                <span class="text-[9px] font-black uppercase tracking-widest text-slate-500">Query Result</span>
                
                <div class="ml-auto flex items-center gap-4">
                    <span id="rowcount-${blockId}" class="text-[9px] font-black text-slate-400"></span>
                </div>
            </div>
            <div class="overflow-x-auto max-h-64 overflow-y-auto x-scrollbar-thin scrollbar-thin">
                <table id="table-${blockId}" class="w-full text-[11px]">
                    <thead id="thead-${blockId}" class="sticky top-0 bg-slate-50 border-b border-slate-200"></thead>
                    <tbody id="tbody-${blockId}"></tbody>
                </table>
            </div>
            <button id="btn-analysis-${blockId}" onclick="triggerStreamConfig('${base64Code}', '${dbId}', 0)" 
                class="flex items-center gap-1.5 px-2 py-1 bg-primary text-white hover:bg-primary/90 text-[9px] font-black rounded-md transition-all uppercase tracking-tighter shadow-sm">
                    <span class="material-symbols-outlined text-[12px]">analytics</span>
                    OPEN  IN  NOTEBOOK
            </button>
        </div>

    `);

    const thead = document.getElementById(`thead-${blockId}`);
    const tbody = document.getElementById(`tbody-${blockId}`);
    const rowcount = document.getElementById(`rowcount-${blockId}`);

    const formData = new FormData();
    formData.append('query', sql);
    formData.append('id', dbId);

    try {
        const response = await fetch('/query-preview', { method: 'POST', body: formData });
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        const PREVIEW_LIMIT = 100;
        let totalRows = 0;
        let dbTotalRows = null; // New state variable to hold the true count

        let buffer = ''; // Add this outside the while loop

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');

            // Keep the last (potentially incomplete) line in the buffer
            buffer = lines.pop();

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const data = JSON.parse(line.slice(6));

                // Render column headers
                if (data.type === 'columns') {
                    thead.innerHTML = `
                        <tr>
                            ${data.content.map(col => `
                                <th class="px-3 py-2 text-left text-[9px] font-black uppercase tracking-wider text-slate-500 whitespace-nowrap">
                                    ${col}
                                </th>
                            `).join('')}
                        </tr>`;
                }
                // Inside the for (const line of lines) loop in runQuery:

if (data.type === 'metadata') {
    dbTotalRows = data.total_rows;
    
    // Minimal Update: Find the button and rewrite its onclick handler
    const analysisBtn = document.getElementById(`btn-analysis-${blockId}`);
    if (analysisBtn) {
        // We use the decoded/original values since they are already in the scope
analysisBtn.setAttribute('onclick', `triggerStreamConfig('${base64Code}', '${dbId}', ${dbTotalRows})`);    }
}                if (data.type === 'rows') {
                    const previousCount = totalRows;
                    totalRows += data.content.length;

                    // Rebuild the HTML completely from state every single time
                    let displayHtml = '';

                    if (dbTotalRows !== null && dbTotalRows !== "Unknown") {
                        // Force the string to a Number so toLocaleString() adds the commas (e.g., 1,000)
                        const formattedTotal = Number(dbTotalRows).toLocaleString();
                        displayHtml = `<span class="text-[9px] font-black text-slate-400">Total: ${formattedTotal}</span> <span class="mx-2 text-slate-300">|</span> `;
                    }

                    displayHtml += `Showing ${totalRows}`;
                    rowcount.innerHTML = displayHtml;
                    if (previousCount < PREVIEW_LIMIT) {
                        const remainingCapacity = PREVIEW_LIMIT - previousCount;
                        const rowsToRender = data.content.slice(0, remainingCapacity);

                        const rowsHtml = rowsToRender.map((row, i) => {
                            const rowIndex = previousCount + i;
                            return `
                            <tr class="${rowIndex % 2 === 0 ? 'bg-white' : 'bg-slate-50/50'} hover:bg-primary-soft/30 transition-colors">
                                ${Object.values(row).map(val => `
                                    <td class="px-3 py-1.5 text-[11px] text-slate-700 font-medium whitespace-nowrap border-b border-slate-100">
                                        ${val === null ? '<span class="text-slate-300 italic">null</span>' : val}
                                    </td>
                                `).join('')}
                            </tr>`;
                        }).join('');

                        tbody.insertAdjacentHTML('beforeend', rowsHtml);

                    }
                }
                if (data.type === 'error') {
                    tbody.innerHTML = `
                        <tr>
                            <td colspan="99" class="px-3 py-3 text-[11px] text-red-500 font-bold">
                                ${data.content}
                            </td>
                        </tr>`;
                }
            }
        }

    } catch (err) {
        tbody.innerHTML = `
            <tr>
                <td colspan="99" class="px-3 py-3 text-[11px] text-red-500 font-bold">
                    Connection lost during execution.
                </td>
            </tr>`;
    }
}

function editQuery(base64Code) {
    if (!base64Code) return;
    const sql = decodeURIComponent(escape(atob(base64Code)));
    console.log("Editing SQL:", sql);
    // TODO: Open a modal or make the div editable
    alert("Editing Query:\n" + sql);
}

// Helper to build the UI box
function buildQueryUI(code, isStreaming = false, dbId = '') {
    if (!code.trim()) return '';

    const blockId = 'qblock-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6);
    const safeCode = isStreaming ? '' : btoa(unescape(encodeURIComponent(code.trim())));
    const buttonState = isStreaming ? 'opacity-50 cursor-not-allowed pointer-events-none' : '';
    const runIcon = isStreaming ? 'sync' : 'play_arrow';
    const runAnim = isStreaming ? 'animate-spin' : '';

    return `
    <div id="${blockId}" class="my-3 bg-slate-900 rounded-xl overflow-hidden border border-slate-700 shadow-md w-full">
        <div class="flex justify-between items-center px-3 py-2 bg-slate-800/80 border-b border-slate-700">
            <div class="flex items-center gap-2 opacity-80">
                <span class="material-symbols-outlined text-[14px] text-primary">terminal</span>
                <span class="text-[9px] uppercase font-black tracking-widest text-primary">SQL Command</span>
            </div>
            <div class="flex gap-2 ${buttonState}">
                <button onclick="editQuery('${safeCode}')" class="flex items-center gap-1 px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-300 text-[9px] font-bold transition-all">
                    <span class="material-symbols-outlined text-[11px]">edit</span>EDIT
                </button>
                <button onclick="runQuery('${safeCode}', '${dbId}', '${blockId}')" class="flex items-center gap-1 px-2 py-1 rounded bg-primary/20 hover:bg-primary/40 text-primary text-[9px] font-bold transition-all">
                    <span class="material-symbols-outlined text-[11px] ${runAnim}">${runIcon}</span>RUN
                </button>
            </div>
        </div>
        <div class="p-3 font-mono text-[12px] text-slate-300 whitespace-pre-wrap overflow-x-auto leading-relaxed">${code.trim()}</div>
    </div>`;
}

function formatAIResponse(raw, dbId) {
    let html = raw;

    html = html.replace(/<query>([\s\S]*?)<\/query>/g, (match, code) => {
        return buildQueryUI(code, false, dbId);
    });

    if (html.includes('<query>') && !html.includes('</query>')) {
        const parts = html.split('<query>');
        const codeSoFar = parts[1].replace(/<\/query>/g, '');
        html = parts[0] + buildQueryUI(codeSoFar, true, dbId);
    }

    html = html.replace(/<comment>([\s\S]*?)<\/comment>/g, (match, comment) => {
        return `<div class="text-xs leading-snug text-slate-700 font-medium">${comment.trim()}</div>`;
    });

    if (html.includes('<comment>') && !html.includes('</comment>')) {
        const parts = html.split('<comment>');
        html = parts[0] + `<div class="text-xs leading-snug text-slate-700 font-medium">${parts[1]}</div>`;
    }

    return html.replace(/<\/?(query|comment)>/g, '');
}

// 4. Enhanced Append Function
function appendMessage(role, text, id = null) {
    const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    let messageHtml = '';

    if (role === 'user') {
        messageHtml = `
            <div class="flex gap-2 flex-row-reverse animate-in fade-in slide-in-from-right-2 duration-300">
                <div class="bg-primary text-white px-2.5 py-2 rounded-xl rounded-tr-none shadow-tactile max-w-[92%]">
                    <p class="text-xs leading-snug font-bold">${text}</p>
                    <span class="text-[8px] text-primary-soft/80 mt-1 block font-black uppercase tracking-wider">You • ${time}</span>
                </div>
            </div>`;
    } else {
        messageHtml = `
            <div class="flex gap-2 animate-in fade-in slide-in-from-left-2 duration-300" id="${id}">
                <div class="w-7 h-7 rounded-xl bg-primary organic-border flex-shrink-0 flex items-center justify-center shadow-tactile">
                    <span class="material-symbols-outlined text-white text-xs" style="font-variation-settings: 'FILL' 1;">auto_awesome</span>
                </div>
                <div class="bg-white px-2.5 py-2 rounded-xl rounded-tl-none border border-slate-100 shadow-data-card max-w-[92%]">
                    <p id="text-${id}" class="text-xs leading-snug text-slate-700 font-medium">${text}</p>
                    <span class="text-[8px] text-slate-400 mt-1 block font-black uppercase tracking-wider">Assistant • ${time}</span>
                </div>
            </div>`;
    }

    chatContainer.insertAdjacentHTML('beforeend', messageHtml);
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

// ----------------------------------------------------------------------------

// Script for system metrics SSE
const eventSource = new EventSource("/system-metrics");

eventSource.onmessage = function (event) {
    const stats = JSON.parse(event.data);
    document.getElementById("cpu-stat").innerText = `CPU: ${stats.cpu}`;
    document.getElementById("ram-stat").innerText = `RAM: ${stats.ram}`;
};

eventSource.onerror = function () {
    console.error("Metrics stream error");
};
