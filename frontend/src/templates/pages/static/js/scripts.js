// Shared chat utilities + SQL proposal cards (no remote execution from chat)

/* ──────────────────────────────────────────────────────────────────────────
   Toast notifications (Spore "Mission Control" style)
   Used by server-rendered flash messages and client-side sporeToast() calls.
   Markup lives in each page's #toast-container; this drives behavior.
   ────────────────────────────────────────────────────────────────────────── */

// Reusable Alpine component: self-dismiss timer, hover-to-pause, animated progress bar.
function sporeToastItem(duration = 5000) {
    return {
        show: false,
        progress: 100,
        _timer: null,
        _start: 0,
        _remaining: duration,
        init() {
            requestAnimationFrame(() => { this.show = true; });
            this.run();
        },
        run() {
            this._start = Date.now();
            this._timer = setInterval(() => {
                const elapsed = Date.now() - this._start;
                this.progress = Math.max(0, (this._remaining - elapsed) / duration * 100);
                if (elapsed >= this._remaining) this.dismiss();
            }, 30);
        },
        pause() {
            clearInterval(this._timer);
            this._remaining -= Date.now() - this._start;
        },
        resume() {
            if (this.show && this._remaining > 0) this.run();
        },
        dismiss() {
            clearInterval(this._timer);
            this.show = false;
            setTimeout(() => { if (this.$root) this.$root.remove(); }, 400);
        }
    };
}

// Programmatically raise a toast (e.g. from fetch handlers). Requires Alpine + #toast-container.
function sporeToast(message, type = 'success') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const isError = type === 'error';
    const el = document.createElement('div');
    el.innerHTML = `
        <div x-data="sporeToastItem()"
             x-show="show"
             x-cloak
             @mouseenter="pause()" @mouseleave="resume()"
             role="alert" aria-live="polite"
             x-transition:enter="transition ease-out duration-500"
             x-transition:enter-start="opacity-0 translate-y-8 scale-95"
             x-transition:enter-end="opacity-100 translate-y-0 scale-100"
             x-transition:leave="transition ease-in duration-300"
             x-transition:leave-start="opacity-100 scale-100"
             x-transition:leave-end="opacity-0 scale-95"
             class="relative overflow-hidden bg-slate-900/95 backdrop-blur-xl border border-slate-800 text-white p-5 rounded-[2rem] shadow-[0_20px_50px_rgba(0,0,0,0.3)] flex items-center gap-5">
            <div class="w-12 h-12 rounded-full flex items-center justify-center shrink-0 relative">
                <div class="absolute inset-0 rounded-full animate-ping opacity-20 ${isError ? 'bg-rose-500' : 'bg-emerald-500'}"></div>
                <div class="relative w-full h-full rounded-full flex items-center justify-center ${isError ? 'bg-rose-500/20 text-rose-400' : 'bg-emerald-500/20 text-emerald-400'}">
                    <span class="material-symbols-outlined text-2xl">${isError ? 'rocket' : 'verified_user'}</span>
                </div>
            </div>
            <div class="flex-1">
                <div class="flex items-center gap-2 mb-0.5">
                    <p class="text-sm font-black uppercase tracking-widest ${isError ? 'text-rose-400' : 'text-emerald-400'} font-headline">Mission Control</p>
                    <span class="text-white text-lg opacity-80 lowercase" style="font-family:'Pacifico',cursive;">${isError ? 'Anomaly' : 'Update'}</span>
                </div>
                <p class="text-xs font-semibold text-slate-400 leading-relaxed">${message}</p>
            </div>
            <button @click="dismiss()" class="group p-2 hover:bg-white/5 rounded-full transition-all">
                <span class="material-symbols-outlined text-slate-500 group-hover:text-white transition-colors">close</span>
            </button>
            <div class="absolute bottom-0 left-0 h-1 rounded-full ${isError ? 'bg-rose-400/70' : 'bg-emerald-400/70'}" :style="\`width: \${progress}%\`"></div>
        </div>
    `;

    container.appendChild(el.firstElementChild);
    if (window.Alpine) Alpine.initTree(container.lastElementChild);
}

window.sporeToast = sporeToast;
window.sporeToastItem = sporeToastItem;

const chatContainer = document.getElementById('chat-messages-container');
let currentMode = 'agent';

function switchToChatView() {
    const landing = document.getElementById('landing-hero');
    const container = document.getElementById('chat-messages-container');
    if (landing) landing.classList.add('hidden');
    if (container) container.classList.remove('hidden');
}

function autoExpand(el) {
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = (Math.min(el.scrollHeight, 150)) + 'px';
}

function escapeHtmlText(s) {
    return String(s ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function getProposalSql(blockId) {
    const block = document.getElementById(blockId);
    const ta = block?.querySelector('.proposal-sql-editor');
    return ta?.value?.trim() || '';
}

function copyProposalSql(blockId) {
    const sql = getProposalSql(blockId);
    if (sql) navigator.clipboard.writeText(sql);
}

function buildQueryUI(code, isStreaming = false, dbId = '', opts = {}) {
    const proposalOnly = opts.proposalOnly !== false;
    if (!code.trim()) return '';

    const blockId = 'qblock-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6);
    const safeCode = isStreaming ? '' : btoa(unescape(encodeURIComponent(code.trim())));
    const buttonState = isStreaming ? 'opacity-50 cursor-not-allowed pointer-events-none' : '';

    const actionButtons = proposalOnly
        ? `
                <button type="button" onclick="copyProposalSql('${blockId}')" class="flex items-center gap-1 px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-300 text-[9px] font-bold transition-all">
                    <span class="material-symbols-outlined text-[11px]">content_copy</span>COPY
                </button>
                <button type="button" onclick="window.openSqlInDataPanel(getProposalSql('${blockId}'), '${dbId}')" class="flex items-center gap-1 px-2 py-1 rounded bg-primary/20 hover:bg-primary/40 text-primary text-[9px] font-bold transition-all">
                    <span class="material-symbols-outlined text-[11px]">open_in_new</span>OPEN IN DATA
                </button>`
        : `
                <button onclick="editQuery('${safeCode}')" class="flex items-center gap-1 px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-300 text-[9px] font-bold transition-all">
                    <span class="material-symbols-outlined text-[11px]">edit</span>EDIT
                </button>
                <button onclick="runQuery('${safeCode}', '${dbId}', '${blockId}')" class="flex items-center gap-1 px-2 py-1 rounded bg-primary/20 hover:bg-primary/40 text-primary text-[9px] font-bold transition-all">
                    <span class="material-symbols-outlined text-[11px]">play_arrow</span>Execute
                </button>`;

    const badge = proposalOnly
        ? '<span class="text-[9px] uppercase font-black tracking-widest text-amber-400">SQL Proposal — you execute</span>'
        : '<span class="text-[9px] uppercase font-black tracking-widest text-primary">SQL Command</span>';

    const codeBlock = proposalOnly && !isStreaming
        ? `<textarea class="proposal-sql-editor w-full bg-transparent border-none focus:ring-0 p-3 font-mono text-[12px] text-slate-300 leading-relaxed resize-y min-h-[4rem] max-h-48" spellcheck="false">${escapeHtmlText(code.trim())}</textarea>`
        : `<div class="p-3 font-mono text-[12px] text-slate-300 whitespace-pre-wrap overflow-x-auto leading-relaxed">${escapeHtmlText(code.trim())}</div>`;

    return `
    <div id="${blockId}" class="my-3 bg-slate-900 rounded-xl overflow-hidden border border-slate-700 shadow-md w-full">
        <div class="flex justify-between items-center px-3 py-2 bg-slate-800/80 border-b border-slate-700">
            <div class="flex items-center gap-2 opacity-80">
                <span class="material-symbols-outlined text-[14px] text-primary">terminal</span>
                ${badge}
            </div>
            <div class="flex gap-2 ${buttonState}">
                ${actionButtons}
            </div>
        </div>
        ${codeBlock}
    </div>`;
}

function formatAIResponse(raw, dbId, opts = {}) {
    let html = raw;

    html = html.replace(/<query>([\s\S]*?)<\/query>/g, (match, code) => {
        return buildQueryUI(code, false, dbId, opts);
    });

    if (html.includes('<query>') && !html.includes('</query>')) {
        const parts = html.split('<query>');
        const codeSoFar = parts[1].replace(/<\/query>/g, '');
        html = parts[0] + buildQueryUI(codeSoFar, true, dbId, opts);
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

function formatAgentMarkdown(text) {
    if (typeof marked !== 'undefined' && marked.parse) {
        return marked.parse(text || '');
    }
    return String(text || '').replace(/\n/g, '<br>');
}

window.formatAIResponse = formatAIResponse;
window.formatAgentMarkdown = formatAgentMarkdown;
window.buildQueryUI = buildQueryUI;
window.switchToChatView = switchToChatView;

function appendMessage(role, text, id = null) {
    switchToChatView();
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

    chatContainer?.insertAdjacentHTML('beforeend', messageHtml);
    if (chatContainer) chatContainer.scrollTop = chatContainer.scrollHeight;
}

function editQuery(base64Code) {
    if (!base64Code) return;
    const sql = decodeURIComponent(escape(atob(base64Code)));
    if (typeof window.openSqlInDataPanel === 'function') {
        window.openSqlInDataPanel(sql);
    } else {
        alert("Editing Query:\n" + sql);
    }
}

// Legacy runQuery kept for Data panel / notebook flows only — not invoked from agent chat
async function runQuery(base64Code, dbId, blockId) {
    if (!base64Code || !dbId) return;
    const sql = decodeURIComponent(escape(atob(base64Code)));

    const queryBlock = document.getElementById(blockId);
    if (!queryBlock) return;

    const existingResult = document.getElementById(`result-${blockId}`);
    if (existingResult) existingResult.remove();

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
        </div>`);

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
        let buffer = '';

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
                    thead.innerHTML = `<tr>${data.content.map(col => `
                        <th class="px-3 py-2 text-left text-[9px] font-black uppercase tracking-wider text-slate-500 whitespace-nowrap">${col}</th>
                    `).join('')}</tr>`;
                }
                if (data.type === 'rows') {
                    const previousCount = totalRows;
                    totalRows += data.content.length;
                    rowcount.textContent = `Showing ${totalRows}`;
                    if (previousCount < PREVIEW_LIMIT) {
                        const remainingCapacity = PREVIEW_LIMIT - previousCount;
                        const rowsToRender = data.content.slice(0, remainingCapacity);
                        tbody.insertAdjacentHTML('beforeend', rowsToRender.map((row, i) => `
                            <tr class="${(previousCount + i) % 2 === 0 ? 'bg-white' : 'bg-slate-50/50'}">
                                ${Object.values(row).map(val => `
                                    <td class="px-3 py-1.5 text-[11px] text-slate-700 font-medium whitespace-nowrap border-b border-slate-100">
                                        ${val === null ? '<span class="text-slate-300 italic">null</span>' : val}
                                    </td>`).join('')}
                            </tr>`).join(''));
                    }
                }
                if (data.type === 'error') {
                    tbody.innerHTML = `<tr><td colspan="99" class="px-3 py-3 text-[11px] text-red-500 font-bold">${data.content}</td></tr>`;
                }
            }
        }
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="99" class="px-3 py-3 text-[11px] text-red-500 font-bold">Connection lost during execution.</td></tr>`;
    }
}

window.runQuery = runQuery;
window.editQuery = editQuery;

document.getElementById('hiddenFileInput')?.addEventListener('change', function (e) {
    const fileInfo = document.getElementById('fileInfo');
    const fileName = document.getElementById('fileName');
    if (this.files && this.files[0]) {
        if (fileName) fileName.textContent = this.files[0].name;
        fileInfo?.classList.remove('hidden');
    }
});

function clearFile() {
    const input = document.getElementById('hiddenFileInput');
    if (input) input.value = '';
    document.getElementById('fileInfo')?.classList.add('hidden');
}

// Only open the metrics stream on pages that actually display it (e.g. chat).
if (document.getElementById("cpu-stat") || document.getElementById("ram-stat")) {
    const eventSource = new EventSource("/system-metrics");
    eventSource.onmessage = function (event) {
        const stats = JSON.parse(event.data);
        const cpu = document.getElementById("cpu-stat");
        const ram = document.getElementById("ram-stat");
        if (cpu) cpu.innerText = `CPU: ${stats.cpu}`;
        if (ram) ram.innerText = `RAM: ${stats.ram}`;
    };
    eventSource.onerror = function () {
        console.error("Metrics stream error");
    };
}
