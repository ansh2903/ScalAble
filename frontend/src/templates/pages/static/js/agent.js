/**
 * Workspace agent: Socket.IO client, artifact renderers, client-tool approval.
 */
(function () {
  let agentRunning = false;
  let currentAssistantEl = null;
  let pendingClientTools = {};
  let streamBuffer = '';
  let streamEl = null;

  const chatContainer = () => document.getElementById('chat-messages-container');
  const messageInput = () => document.getElementById('messageInput');
  const sendBtn = () => document.getElementById('sendMessageBtn');
  const stopBtn = () => document.getElementById('agent-stop-btn');
  const statusEl = () => document.getElementById('system-status');
  const landingHero = () => document.getElementById('landing-hero');

  const agentSocket = window.sporeSocket || (window.sporeSocket = typeof io !== 'undefined' ? io() : null);

  function getWorkspaceId() {
    return window.SPORE_WORKSPACE?.id
      || (typeof window.getActiveWorkspaceId === 'function' ? window.getActiveWorkspaceId() : null);
  }

  function getSelectedDbId() {
    return document.getElementById('selected_db_id')?.value || '';
  }

  function switchToChatView() {
    landingHero()?.classList.add('hidden');
    chatContainer()?.classList.remove('hidden');
  }

  function showLanding() {
    const container = chatContainer();
    if (container) {
      container.innerHTML = '';
      container.classList.add('hidden');
    }
    landingHero()?.classList.remove('hidden');
    currentAssistantEl = null;
    clearStreamEl();
    updateContextUsage(0, null);
    setAgentRunning(false);
    setAgentStatus('Agent: Standby');
  }

  function resetAgent() {
    agentSocket?.emit('agent_reset', { workspace_id: getWorkspaceId() });
    showLanding();
  }

  function updateContextUsage(used, limit, opts = {}) {
    const el = document.getElementById('agent-context-usage');
    if (!el) return;

    if (opts.show === false) {
      el.classList.add('hidden');
      return;
    }
    if (opts.show === true) {
      el.classList.remove('hidden');
    }

    const lim = limit ?? (parseInt(el.dataset.limit, 10) || 2048);
    if (limit != null) el.dataset.limit = String(lim);
    const clamped = Boolean(opts.clamped);
    const pct = lim > 0 ? Math.min(100, (used / lim) * 100) : 0;
    let barColor = 'bg-slate-400';
    let textColor = 'text-slate-400';
    if (clamped) {
      barColor = 'bg-amber-500';
      textColor = 'text-amber-500';
    } else if (pct > 90) {
      barColor = 'bg-red-500';
      textColor = 'text-red-500';
    } else if (pct > 75) {
      barColor = 'bg-amber-500';
      textColor = 'text-amber-500';
    }
    const suffix = clamped ? ' (model max)' : '';
    el.innerHTML = `
      <span class="text-[8px] font-mono ${textColor}">ctx ${used} / ${lim}${suffix}</span>
      <div class="w-16 h-1 bg-slate-200 rounded-full overflow-hidden mt-0.5 ml-auto">
        <div class="h-full ${barColor} transition-all" style="width:${pct}%"></div>
      </div>`;
  }

  function setAgentStatus(text) {
    const el = statusEl();
    if (el) el.textContent = text;
  }

  function setAgentRunning(running) {
    agentRunning = running;
    stopBtn()?.classList.toggle('hidden', !running);
    sendBtn()?.classList.toggle('opacity-50', running);
    sendBtn()?.classList.toggle('pointer-events-none', running);
  }

  function escapeHtml(s) {
    return String(s ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function appendUserMessage(text) {
    switchToChatView();
    const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    chatContainer()?.insertAdjacentHTML('beforeend', `
      <div class="flex gap-2 flex-row-reverse animate-in fade-in slide-in-from-right-2 duration-300">
        <div class="bg-primary text-white px-2.5 py-2 rounded-xl rounded-tr-none shadow-tactile max-w-[92%]">
          <p class="text-xs leading-snug font-bold whitespace-pre-wrap">${escapeHtml(text)}</p>
          <span class="text-[8px] text-primary-soft/80 mt-1 block font-black uppercase tracking-wider">You • ${time}</span>
        </div>
      </div>`);
    scrollChat();
  }

  function appendAssistantShell(id) {
    switchToChatView();
    const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    chatContainer()?.insertAdjacentHTML('beforeend', `
      <div class="flex gap-2 animate-in fade-in slide-in-from-left-2 duration-300" id="${id}">
        <div class="w-7 h-7 rounded-xl bg-primary organic-border flex-shrink-0 flex items-center justify-center shadow-tactile">
          <span class="material-symbols-outlined text-white text-xs" style="font-variation-settings: 'FILL' 1;">smart_toy</span>
        </div>
        <div class="bg-white px-2.5 py-2 rounded-xl rounded-tl-none border border-slate-100 shadow-data-card max-w-[92%] min-w-0 flex-1">
          <div id="body-${id}" class="text-xs leading-snug text-slate-700 font-medium space-y-2"></div>
          <span class="text-[8px] text-slate-400 mt-1 block font-black uppercase tracking-wider">Agent • ${time}</span>
        </div>
      </div>`);
    scrollChat();
    return document.getElementById(`body-${id}`);
  }

  function scrollChat() {
    const c = chatContainer();
    if (c) c.scrollTop = c.scrollHeight;
  }

  function clearStreamEl() {
    streamEl?.remove();
    streamEl = null;
    streamBuffer = '';
  }

  function stripAgentTags(text) {
    return String(text || '')
      .replace(/<thought>[\s\S]*?<\/thought>/gi, '')
      .replace(/<tool[^>]*>[\s\S]*?<\/tool>/gi, '')
      .replace(/<final>[\s\S]*?<\/final>/gi, '')
      .replace(/<comment>[\s\S]*?<\/comment>/gi, '')
      .replace(/<\/?(?:thought|tool|final|comment)[^>]*>/gi, '')
      .trim();
  }

  function ensureStreamEl(bodyEl) {
    if (!bodyEl) return null;
    if (streamEl && bodyEl.contains(streamEl)) return streamEl;
    const id = `agent-stream-${Date.now()}`;
    bodyEl.insertAdjacentHTML('beforeend', `
      <div id="${id}" class="agent-stream text-[10px] text-slate-500 font-mono whitespace-pre-wrap border-l-2 border-slate-200 pl-2 min-h-[1em]"></div>`);
    streamEl = document.getElementById(id);
    return streamEl;
  }

  function appendTokenStream(bodyEl, token) {
    if (!bodyEl || !token) return;
    streamBuffer += token;
    const el = ensureStreamEl(bodyEl);
    if (el) {
      const visible = stripAgentTags(streamBuffer);
      el.textContent = visible || streamBuffer.replace(/<[^>]+>/g, '');
      scrollChat();
    }
  }

  function appendPlanStep(bodyEl, content, step) {
    clearStreamEl();
    if (!bodyEl) return;
    const id = `plan-${Date.now()}-${step}`;
    bodyEl.insertAdjacentHTML('beforeend', `
      <div id="${id}" class="flex items-start gap-2 px-2 py-1.5 rounded-lg bg-slate-50 border border-slate-100">
        <span class="material-symbols-outlined text-[12px] text-primary mt-0.5">route</span>
        <span class="text-[10px] font-bold text-slate-600">${escapeHtml(content)}</span>
      </div>`);
    scrollChat();
  }

  function appendThought(bodyEl, content) {
    clearStreamEl();
    if (!bodyEl || !content) return;
    bodyEl.insertAdjacentHTML('beforeend', `
      <p class="text-[10px] text-slate-500 italic border-l-2 border-primary/30 pl-2">${escapeHtml(content)}</p>`);
    scrollChat();
  }

  function appendToolCall(bodyEl, tool, args) {
    clearStreamEl();
    if (!bodyEl) return;
    bodyEl.insertAdjacentHTML('beforeend', `
      <details class="rounded-lg border border-slate-200 overflow-hidden">
        <summary class="px-2 py-1.5 bg-slate-50 text-[9px] font-black uppercase tracking-widest text-slate-500 cursor-pointer">
          Tool: ${escapeHtml(tool)}
        </summary>
        <pre class="p-2 text-[9px] font-mono text-slate-600 overflow-x-auto">${escapeHtml(JSON.stringify(args, null, 2))}</pre>
      </details>`);
    scrollChat();
  }

  function appendFinal(bodyEl, content) {
    clearStreamEl();
    if (!bodyEl) return;
    const html = typeof window.formatAgentMarkdown === 'function'
      ? window.formatAgentMarkdown(content)
      : escapeHtml(content).replace(/\n/g, '<br>');
    bodyEl.insertAdjacentHTML('beforeend', `<div class="agent-final prose prose-sm max-w-none">${html}</div>`);
    scrollChat();
  }

  function buildSqlProposalCard(raw, dbId) {
    if (typeof window.formatAIResponse === 'function') {
      return window.formatAIResponse(raw, dbId, { proposalOnly: true });
    }
    return `<pre class="text-[10px] font-mono">${escapeHtml(raw)}</pre>`;
  }

  function appendSqlProposal(bodyEl, raw, sourceId) {
    clearStreamEl();
    if (!bodyEl) return;
    const dbId = sourceId || getSelectedDbId();
    bodyEl.insertAdjacentHTML('beforeend', buildSqlProposalCard(raw, dbId));
    scrollChat();
  }

  function appendTableArtifact(bodyEl, columns, rows, rowCount) {
    clearStreamEl();
    if (!bodyEl || !columns?.length) return;
    const head = columns.map((c) => `
      <th class="px-2 py-1 text-left text-[8px] font-black uppercase text-slate-500">${escapeHtml(c)}</th>`).join('');
    const body = (rows || []).slice(0, 50).map((row, i) => `
      <tr class="${i % 2 ? 'bg-slate-50/50' : ''}">
        ${columns.map((c) => `<td class="px-2 py-1 text-[10px] whitespace-nowrap">${escapeHtml(row[c])}</td>`).join('')}
      </tr>`).join('');
    const chartId = `chart-table-${Date.now()}`;
    bodyEl.insertAdjacentHTML('beforeend', `
      <div class="rounded-xl border border-slate-200 overflow-hidden">
        <div class="px-2 py-1 bg-slate-50 border-b border-slate-100 flex justify-between">
          <span class="text-[9px] font-black uppercase text-slate-500">Local data</span>
          <span class="text-[9px] text-slate-400">${rowCount ?? rows?.length ?? 0} rows</span>
        </div>
        <div class="overflow-x-auto max-h-48">
          <table class="w-full"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>
        </div>
      </div>`);
    scrollChat();
  }

  function appendChartArtifact(bodyEl, option) {
    clearStreamEl();
    if (!bodyEl || !option || typeof echarts === 'undefined') return;
    const chartId = `agent-chart-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    bodyEl.insertAdjacentHTML('beforeend', `
      <div class="rounded-xl border border-slate-200 overflow-hidden p-1">
        <div id="${chartId}" class="w-full h-48 min-h-[120px]"></div>
      </div>`);
    const el = document.getElementById(chartId);
    if (el && !option._placeholder) {
      const inst = echarts.init(el);
      inst.setOption(option);
      new ResizeObserver(() => inst.resize()).observe(el);
    } else if (el) {
      el.innerHTML = `<p class="text-[10px] text-slate-400 text-center p-4">${escapeHtml(option._placeholder || 'No chart data')}</p>`;
    }
    scrollChat();
  }

  function appendClientToolApproval(bodyEl, event) {
    if (!bodyEl) return;
    const { request_id, tool, args } = event;
    const isCodeTool = tool === 'run_python' || tool === 'add_notebook_cell';
    const codeText = args.code || '';
    const preview = isCodeTool
      ? codeText
      : JSON.stringify(args, null, 2);

    const cardId = `client-tool-${request_id}`;
    const bodyContent = isCodeTool
      ? `<textarea class="agent-edit-code w-full p-2 text-[10px] font-mono text-slate-700 max-h-40 min-h-[4rem] resize-y border border-amber-100 rounded bg-white focus:ring-1 focus:ring-primary/30" spellcheck="false">${escapeHtml(preview)}</textarea>`
      : `<pre class="p-2 text-[10px] font-mono text-slate-700 max-h-32 overflow-auto whitespace-pre-wrap">${escapeHtml(preview)}</pre>`;

    bodyEl.insertAdjacentHTML('beforeend', `
      <div id="${cardId}" class="rounded-xl border border-amber-200 bg-amber-50/50 overflow-hidden">
        <div class="px-2 py-1.5 border-b border-amber-100 flex items-center gap-2">
          <span class="material-symbols-outlined text-[14px] text-amber-600">pending_actions</span>
          <span class="text-[9px] font-black uppercase tracking-widest text-amber-800">Approve: ${escapeHtml(tool)}</span>
        </div>
        ${bodyContent}
        <div class="flex gap-2 p-2 border-t border-amber-100">
          <button type="button" data-approve="${request_id}"
            class="flex-1 px-2 py-1.5 bg-primary text-white text-[9px] font-black rounded-lg uppercase">Accept</button>
          <button type="button" data-reject="${request_id}"
            class="px-2 py-1.5 bg-white border border-slate-200 text-[9px] font-black rounded-lg uppercase text-slate-500">Reject</button>
        </div>
      </div>`);

    const card = document.getElementById(cardId);
    card?.querySelector(`[data-approve="${request_id}"]`)?.addEventListener('click', () => {
      const effectiveArgs = { ...args };
      if (isCodeTool) {
        const ta = card.querySelector('.agent-edit-code');
        if (ta) effectiveArgs.code = ta.value;
      }
      executeClientTool(request_id, tool, effectiveArgs, true);
      card.querySelector('.flex.gap-2')?.remove();
    });
    card?.querySelector(`[data-reject="${request_id}"]`)?.addEventListener('click', () => {
      agentSocket?.emit('agent_tool_result', { request_id, ok: false, error: 'Rejected by user' });
      card.querySelector('.flex.gap-2')?.remove();
    });
    pendingClientTools[request_id] = { tool, args };
    scrollChat();
  }

  async function executeClientTool(requestId, tool, args, approved) {
    if (!approved) return;
    let result = { ok: false, error: 'Unknown tool' };

    try {
      if (tool === 'run_python') {
        result = await runPythonInKernel(args.code || '');
      } else if (tool === 'add_notebook_cell') {
        result = addNotebookCell(args.type || 'python', args.code || '');
      } else if (tool === 'add_dashboard_widget') {
        result = addDashboardWidget(args);
      } else {
        result = { ok: false, error: `Unsupported client tool: ${tool}` };
      }
    } catch (e) {
      result = { ok: false, error: String(e.message || e) };
    }

    agentSocket?.emit('agent_tool_result', { request_id: requestId, ...result });
    delete pendingClientTools[requestId];
  }

  function runPythonInKernel(code) {
    return new Promise((resolve) => {
      if (!agentSocket || !code.trim()) {
        resolve({ ok: false, error: 'No code or socket' });
        return;
      }
      const cellId = `agent-${Date.now()}`;
      const outputs = [];
      const timeout = setTimeout(() => {
        agentSocket.off('kernel_output', handler);
        resolve({ ok: true, outputs });
      }, 30000);

      function handler(chunk) {
        if (chunk.cell_id !== cellId) return;
        outputs.push(chunk);
        if (chunk.type === 'done' || chunk.type === 'error') {
          clearTimeout(timeout);
          agentSocket.off('kernel_output', handler);
          resolve({ ok: chunk.type !== 'error', outputs });
        }
      }

      agentSocket.on('kernel_output', handler);
      agentSocket.emit('kernel_execute', { cell_id: cellId, code });
    });
  }

  function addNotebookCell(type, code) {
    if (typeof window.sporeAddNotebookCell === 'function') {
      const cellId = window.sporeAddNotebookCell(type, code);
      if (typeof openNotebookPanel === 'function') openNotebookPanel();
      return { ok: true, cell_id: cellId };
    }
    return { ok: false, error: 'Notebook not available' };
  }

  function addDashboardWidget(args) {
    if (typeof window.sporeAddDashboardWidget === 'function') {
      const widgetId = window.sporeAddDashboardWidget(args);
      if (typeof openDashboardPanel === 'function') openDashboardPanel();
      return { ok: true, widget_id: widgetId };
    }
    return { ok: false, error: 'Dashboard not available' };
  }

  function parseMessageContext(message) {
    const relationMatch = message.match(/@([\w./:-]+)/);
    const viewMatch = message.match(/#(notebook|dashboard|data)/i);
    return {
      relation_ref: relationMatch ? relationMatch[1] : null,
      active_view: viewMatch ? viewMatch[1].toLowerCase() : (window.SPORE_WORKSPACE_STATE?.active_view || 'data'),
      source_id: getSelectedDbId() || null,
    };
  }

  let mentionDatasets = [];
  let mentionState = { open: false, start: 0, end: 0, query: '', activeIndex: 0 };

  function mentionMenuEl() {
    return document.getElementById('agent-mention-menu');
  }

  async function loadMentionDatasets() {
    try {
      const res = await fetch('/api/datasets');
      if (res.ok) {
        const data = await res.json();
        mentionDatasets = (data.datasets || []).map((d) => ({
          ref: d.ref || d.name,
          label: d.label || d.ref,
          columns: d.columns || [],
        }));
        return;
      }
    } catch (_) { /* fallback below */ }

    const wsId = getWorkspaceId();
    if (!wsId) return;
    try {
      const res = await fetch(`/api/workspaces/${encodeURIComponent(wsId)}/relations`);
      if (res.ok) {
        const data = await res.json();
        mentionDatasets = Object.values(data.relations || {}).map((r) => ({
          ref: r.ref || r.name,
          label: r.label || r.ref,
          columns: r.columns || [],
        }));
      }
    } catch (_) { /* ignore */ }
  }

  function hideMentionMenu() {
    mentionState.open = false;
    mentionMenuEl()?.classList.add('hidden');
  }

  function highlightMentionItem(items) {
    items.forEach((el, i) => {
      el.classList.toggle('bg-primary/5', i === mentionState.activeIndex);
    });
  }

  function applyMentionSelection(ref) {
    const input = messageInput();
    if (!input || !ref) return;
    const before = input.value.slice(0, mentionState.start);
    const after = input.value.slice(mentionState.end);
    input.value = `${before}@${ref} ${after}`;
    const pos = before.length + ref.length + 2;
    input.setSelectionRange(pos, pos);
    hideMentionMenu();
    input.focus();
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, 150)}px`;
  }

  function updateMentionMenu() {
    const input = messageInput();
    const menu = mentionMenuEl();
    if (!input || !menu) return;

    const val = input.value;
    const caret = input.selectionStart ?? val.length;
    const before = val.slice(0, caret);
    const atMatch = before.match(/@([\w./:-]*)$/);
    if (!atMatch) {
      hideMentionMenu();
      return;
    }

    mentionState.start = caret - atMatch[0].length;
    mentionState.end = caret;
    mentionState.query = atMatch[1].toLowerCase();
    mentionState.open = true;
    mentionState.activeIndex = 0;

    const q = mentionState.query;
    const matches = mentionDatasets
      .filter((d) => {
        const ref = (d.ref || '').toLowerCase();
        const label = (d.label || '').toLowerCase();
        return !q || ref.includes(q) || label.includes(q);
      })
      .slice(0, 8);

    if (!matches.length) {
      hideMentionMenu();
      return;
    }

    menu.innerHTML = matches.map((d, i) => {
      const cols = (d.columns || []).slice(0, 3).join(', ');
      return `<button type="button" class="mention-item w-full text-left px-2 py-1.5 text-[10px] hover:bg-primary/10 ${i === 0 ? 'bg-primary/5' : ''}" data-ref="${escapeHtml(d.ref)}" data-idx="${i}">
        <span class="font-bold text-slate-800">@${escapeHtml(d.ref)}</span>${cols ? `<span class="text-slate-400 ml-1 truncate">${escapeHtml(cols)}</span>` : ''}
      </button>`;
    }).join('');
    menu.classList.remove('hidden');

    menu.querySelectorAll('.mention-item').forEach((btn) => {
      btn.addEventListener('mousedown', (e) => {
        e.preventDefault();
        applyMentionSelection(btn.dataset.ref);
      });
    });
  }

  function handleMentionKeydown(e) {
    if (!mentionState.open) return false;
    const menu = mentionMenuEl();
    const items = menu?.querySelectorAll('.mention-item');
    if (!items?.length) return false;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      mentionState.activeIndex = Math.min(mentionState.activeIndex + 1, items.length - 1);
      highlightMentionItem(items);
      return true;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      mentionState.activeIndex = Math.max(mentionState.activeIndex - 1, 0);
      highlightMentionItem(items);
      return true;
    }
    if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault();
      const ref = items[mentionState.activeIndex]?.dataset.ref;
      if (ref) applyMentionSelection(ref);
      return true;
    }
    if (e.key === 'Escape') {
      e.preventDefault();
      hideMentionMenu();
      return true;
    }
    return false;
  }

  function handleAgentEvent(event, bodyEl) {
    if (!event || !bodyEl) return;

    switch (event.type) {
      case 'plan_step':
        appendPlanStep(bodyEl, event.content, event.step);
        setAgentStatus(`Agent: Step ${event.step}`);
        break;
      case 'thought':
        appendThought(bodyEl, event.content);
        break;
      case 'token':
        appendTokenStream(bodyEl, event.content);
        break;
      case 'tool_call':
        appendToolCall(bodyEl, event.tool, event.args || {});
        break;
      case 'tool_result':
        if (!event.ok && event.error) {
          bodyEl.insertAdjacentHTML('beforeend', `<p class="text-[10px] text-red-500 font-bold">${escapeHtml(event.error)}</p>`);
        }
        break;
      case 'sql_proposal':
        appendSqlProposal(bodyEl, event.content, event.source_id);
        break;
      case 'artifact':
        if (event.artifact === 'table') {
          appendTableArtifact(bodyEl, event.columns, event.rows, event.row_count);
        } else if (event.artifact === 'chart') {
          appendChartArtifact(bodyEl, event.option);
        }
        break;
      case 'client_tool_request':
        appendClientToolApproval(bodyEl, event);
        break;
      case 'context':
        updateContextUsage(event.used ?? 0, event.limit, {
          modelMax: event.model_max,
          clamped: event.clamped,
          show: event.show,
        });
        break;
      case 'reset_done':
        break;
      case 'final':
        appendFinal(bodyEl, event.content);
        break;
      case 'error':
        bodyEl.insertAdjacentHTML('beforeend', `<p class="text-[10px] text-red-500 font-bold">${escapeHtml(event.content)}</p>`);
        break;
      case 'interrupted':
        clearStreamEl();
        setAgentStatus('Agent: Stopped');
        break;
      case 'done':
        setAgentRunning(false);
        setAgentStatus('Agent: Standby');
        break;
      default:
        break;
    }
    scrollChat();
  }

  function runAgent(message) {
    if (!agentSocket) {
      alert('Socket connection unavailable');
      return;
    }
    if (agentRunning) return;

    const trimmed = message.trim();
    if (!trimmed) return;

    appendUserMessage(trimmed);
    messageInput().value = '';
    messageInput().style.height = 'auto';
    hideMentionMenu();

    const msgId = `msg-${Date.now()}`;
    currentAssistantEl = appendAssistantShell(msgId);
    clearStreamEl();
    setAgentRunning(true);
    setAgentStatus('Agent: Running…');

    const context = parseMessageContext(trimmed);
    agentSocket.emit('agent_run', {
      message: trimmed,
      workspace_id: getWorkspaceId(),
      context,
    });
  }

  function bindUI() {
    const input = messageInput();
    const btn = sendBtn();

    input?.addEventListener('focus', () => {
      loadMentionDatasets();
    });

    input?.addEventListener('input', function () {
      this.style.height = 'auto';
      this.style.height = `${Math.min(this.scrollHeight, 150)}px`;
      updateMentionMenu();
    });

    input?.addEventListener('keydown', (e) => {
      if (handleMentionKeydown(e)) return;
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (input.value.trim()) btn?.click();
      }
    });

    btn?.addEventListener('click', () => runAgent(input?.value || ''));

    stopBtn()?.addEventListener('click', () => {
      agentSocket?.emit('agent_interrupt');
      setAgentRunning(false);
      setAgentStatus('Agent: Stopped');
    });

    document.getElementById('agent-new-chat-btn')?.addEventListener('click', () => {
      if (agentRunning) {
        agentSocket?.emit('agent_interrupt');
      }
      resetAgent();
    });

    agentSocket?.on('agent_event', (event) => {
      handleAgentEvent(event, currentAssistantEl);
      if (event.type === 'done' || event.type === 'error' || event.type === 'interrupted') {
        setAgentRunning(false);
        if (event.type !== 'interrupted') setAgentStatus('Agent: Standby');
      }
    });

    document.getElementById('selected_db_id')?.addEventListener('change', updateConnChip);
    updateConnChip();
    updateContextChip();
    resetAgent();
  }

  function updateConnChip() {
    const sel = document.getElementById('selected_db_id');
    const label = document.getElementById('chat-conn-label');
    if (!sel || !label) return;
    const opt = sel.options[sel.selectedIndex];
    label.textContent = opt?.text ? opt.text.slice(0, 18) : 'Source for /';
  }

  function updateContextChip() {
    const chip = document.getElementById('agent-context-chip');
    const view = window.SPORE_WORKSPACE_STATE?.active_view || 'data';
    if (chip) chip.textContent = `${view} view`;
  }

  window.runWorkspaceAgent = runAgent;
  window.openSqlInDataPanel = function openSqlInDataPanel(sql, dbId) {
    const id = dbId || getSelectedDbId();
    const select = document.getElementById('selected_db_id');
    if (select && id) select.value = id;
    if (typeof openDataPanel === 'function') openDataPanel();
    window.monacoReady?.then(() => {
      if (window.dataEditor) {
        window.dataEditor.setValue(sql || '');
        window.dataEditor.focus();
      }
    });
  };

  document.addEventListener('DOMContentLoaded', bindUI);
})();
