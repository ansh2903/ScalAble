/**
 * Dashboard: Gridstack layout + ECharts widgets bound to materialized streams.
 */

(function () {
  const PALETTES = {
    default: ['#00A36C', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4'],
    emerald: ['#00A36C', '#065f46', '#34d399', '#6ee7b7'],
    ocean: ['#0ea5e9', '#0284c7', '#0369a1', '#075985'],
  };

  const WIDGET_TYPES = [
    { type: 'bar', icon: 'bar_chart', label: 'Bar' },
    { type: 'line', icon: 'show_chart', label: 'Line' },
    { type: 'area', icon: 'area_chart', label: 'Area' },
    { type: 'pie', icon: 'pie_chart', label: 'Pie' },
    { type: 'scatter', icon: 'scatter_plot', label: 'Scatter' },
    { type: 'kpi', icon: 'pin', label: 'KPI' },
    { type: 'table', icon: 'table', label: 'Table' },
    { type: 'map', icon: 'map', label: 'Map' },
  ];

  let dashboardState = { title: '', widgets: [], layout: { columns: 12 }, metadata: {} };
  let grid = null;
  let chartInstances = {};
  let editMode = true;
  let selectedWidgetId = null;
  let _hydrating = false;
  let _saveTimer = null;

  function defaultDashboard() {
    const ws = window.SPORE_WORKSPACE;
    return {
      title: ws?.name || 'Dashboard',
      widgets: [],
      layout: { columns: 12 },
      metadata: {},
    };
  }

  function loadState() {
    if (typeof window.getWorkspaceDashboardState === 'function') {
      const s = window.getWorkspaceDashboardState();
      if (s && typeof s === 'object') {
        dashboardState = {
          ...defaultDashboard(),
          ...s,
          widgets: Array.isArray(s.widgets) ? s.widgets : [],
        };
      }
    }
  }

  function scheduleSave() {
    if (_hydrating) return;
    clearTimeout(_saveTimer);
    _saveTimer = setTimeout(() => {
      if (window.SPORE_WORKSPACE_STATE) {
        window.SPORE_WORKSPACE_STATE.dashboard = dashboardState;
      }
      if (typeof window.saveWorkspaceStatePatch === 'function') {
        window.saveWorkspaceStatePatch({ dashboard: dashboardState });
      }
      updateHeader();
    }, 400);
  }

  function updateHeader() {
    const countEl = document.getElementById('dashboard-widget-count');
    if (countEl) countEl.textContent = String(dashboardState.widgets.length);
  }

  function genId() {
    return `w_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
  }

  function findWidget(id) {
    return dashboardState.widgets.find((w) => w.id === id);
  }

  function nextLayoutSlot() {
    const widgets = dashboardState.widgets;
    let maxY = 0;
    widgets.forEach((w) => {
      const ly = (w.layout?.y || 0) + (w.layout?.h || 2);
      if (ly > maxY) maxY = ly;
    });
    return { x: 0, y: maxY, w: 6, h: 2 };
  }

  function createWidget(type) {
    const layout = nextLayoutSlot();
    return {
      id: genId(),
      type,
      title: `${type.charAt(0).toUpperCase()}${type.slice(1)}`,
      source: { kind: 'stream', ref: '' },
      transform: { dimensions: [], measures: [], limit: 500 },
      encoding: { x: '', y: '' },
      style: { palette: 'default', showLegend: true },
      layout,
    };
  }

  async function fetchStreams() {
    const base = typeof window.getWorkspaceApiBase === 'function' ? window.getWorkspaceApiBase() : null;
    if (!base) return [];
    try {
      const res = await fetch(`${base}/relations`);
      const data = await res.json();
      return Object.keys(data.relations || {});
    } catch {
      return [];
    }
  }

  async function queryWidgetData(widget) {
    const ref = widget.source?.ref;
    if (!ref) throw new Error('No stream selected');
    const res = await fetch('/api/widgets/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        stream: ref,
        transform: widget.transform,
        limit: widget.transform?.limit || 500,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Query failed');
    return data;
  }

  function buildEchartsOption(widget, rows, columns) {
    const type = (widget.type || 'bar').toLowerCase();
    const enc = widget.encoding || {};
    const xKey = enc.x || columns[0];
    const yKey = enc.y || columns[1] || columns[0];
    const palette = PALETTES[widget.style?.palette] || PALETTES.default;

    if (type === 'kpi') {
      const row = rows[0] || {};
      const val = yKey && row[yKey] !== undefined ? row[yKey] : Object.values(row)[0];
      return { _kpi: String(val ?? '—') };
    }

    if (type === 'table') {
      return { _table: { columns, rows } };
    }

    if (type === 'map') {
      const names = rows.map((r) => String(r[enc.x || columns[0]] ?? ''));
      const vals = rows.map((r) => Number(r[enc.y || columns[1]]) || 0);
      return {
        color: palette,
        tooltip: { trigger: 'axis' },
        grid: { left: 48, right: 16, top: 24, bottom: 48 },
        xAxis: { type: 'category', data: names, axisLabel: { rotate: 35, fontSize: 9 } },
        yAxis: { type: 'value' },
        series: [{ type: 'bar', data: vals, itemStyle: { color: palette[0] } }],
      };
    }

    const categories = rows.map((r) => String(r[xKey] ?? ''));
    const values = rows.map((r) => Number(r[yKey]) || 0);

    if (type === 'pie') {
      return {
        color: palette,
        tooltip: { trigger: 'item' },
        legend: widget.style?.showLegend !== false ? { bottom: 0 } : undefined,
        series: [{
          type: 'pie',
          radius: ['35%', '65%'],
          data: categories.map((c, i) => ({ name: c, value: values[i] })),
        }],
      };
    }

    const seriesType = type === 'line' ? 'line' : type === 'area' ? 'line' : type === 'scatter' ? 'scatter' : 'bar';
    return {
      color: palette,
      tooltip: { trigger: 'axis' },
      legend: widget.style?.showLegend !== false ? { top: 0 } : undefined,
      grid: { left: 48, right: 16, top: 32, bottom: 32 },
      xAxis: { type: 'category', data: categories, axisLabel: { fontSize: 10 } },
      yAxis: { type: 'value', axisLabel: { fontSize: 10 } },
      series: [{
        type: seriesType,
        data: values,
        areaStyle: type === 'area' ? {} : undefined,
        smooth: type === 'line' || type === 'area',
      }],
    };
  }

  function renderWidgetBody(widget, container, queryResult) {
    const rows = queryResult?.rows || [];
    const columns = queryResult?.columns || [];
    container.innerHTML = '';

    if (chartInstances[widget.id]) {
      chartInstances[widget.id].dispose();
      delete chartInstances[widget.id];
    }

    const opt = buildEchartsOption(widget, rows, columns);

    if (opt._kpi) {
      const el = document.createElement('div');
      el.className = 'flex items-center justify-center h-full text-3xl font-black text-slate-900';
      el.textContent = opt._kpi;
      container.appendChild(el);
      return;
    }

    if (opt._table) {
      const wrap = document.createElement('div');
      wrap.className = 'overflow-auto h-full text-[10px] font-mono';
      const table = document.createElement('table');
      table.className = 'w-full border-collapse';
      const thead = document.createElement('thead');
      const hr = document.createElement('tr');
      opt._table.columns.forEach((c) => {
        const th = document.createElement('th');
        th.className = 'sticky top-0 bg-slate-50 border-b border-slate-200 px-2 py-1 text-left';
        th.textContent = c;
        hr.appendChild(th);
      });
      thead.appendChild(hr);
      table.appendChild(thead);
      const tbody = document.createElement('tbody');
      opt._table.rows.slice(0, 100).forEach((row) => {
        const tr = document.createElement('tr');
        opt._table.columns.forEach((c) => {
          const td = document.createElement('td');
          td.className = 'border-b border-slate-100 px-2 py-0.5';
          td.textContent = row[c];
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      wrap.appendChild(table);
      container.appendChild(wrap);
      return;
    }

    const chartEl = document.createElement('div');
    chartEl.className = 'w-full h-full min-h-[120px]';
    container.appendChild(chartEl);
    if (typeof echarts !== 'undefined') {
      const inst = echarts.init(chartEl);
      chartInstances[widget.id] = inst;
      inst.setOption(opt);
      new ResizeObserver(() => inst.resize()).observe(container);
    }
  }

  async function refreshWidget(widgetId) {
    const widget = findWidget(widgetId);
    if (!widget) return;
    const body = document.querySelector(`[data-widget-body="${widgetId}"]`);
    if (!body) return;
    body.innerHTML = '<p class="text-[10px] text-slate-400 p-4">Loading…</p>';
    try {
      const result = await queryWidgetData(widget);
      renderWidgetBody(widget, body, result);
      if (result.columns?.length && !widget.encoding.x) {
        widget.encoding.x = result.columns[0];
        if (result.columns[1]) widget.encoding.y = result.columns[1];
      }
    } catch (e) {
      body.innerHTML = `<p class="text-[10px] text-red-500 p-4 font-mono">${e.message}</p>`;
    }
  }

  function buildWidgetElement(widget) {
    const item = document.createElement('div');
    item.className = 'grid-stack-item';
    item.setAttribute('gs-id', widget.id);
    item.setAttribute('gs-x', String(widget.layout?.x ?? 0));
    item.setAttribute('gs-y', String(widget.layout?.y ?? 0));
    item.setAttribute('gs-w', String(widget.layout?.w ?? 4));
    item.setAttribute('gs-h', String(widget.layout?.h ?? 2));

    const content = document.createElement('div');
    content.className = 'grid-stack-item-content rounded-xl border border-slate-200 bg-white shadow-data-card flex flex-col overflow-hidden';

    const header = document.createElement('div');
    header.className = 'flex items-center justify-between px-3 py-1.5 border-b border-slate-100 shrink-0';
    header.innerHTML = `
      <span class="text-[10px] font-black uppercase tracking-widest text-slate-700 truncate">${widget.title || widget.type}</span>
      <div class="flex items-center gap-0.5 dashboard-widget-actions">
        <button type="button" data-action="config" class="p-1 rounded hover:bg-slate-100 text-slate-400" title="Configure"><span class="material-symbols-outlined text-[14px]">tune</span></button>
        <button type="button" data-action="refresh" class="p-1 rounded hover:bg-slate-100 text-slate-400" title="Refresh"><span class="material-symbols-outlined text-[14px]">refresh</span></button>
        <button type="button" data-action="delete" class="p-1 rounded hover:bg-red-50 text-red-400" title="Delete"><span class="material-symbols-outlined text-[14px]">close</span></button>
      </div>`;

    const body = document.createElement('div');
    body.className = 'flex-1 min-h-0 p-1';
    body.setAttribute('data-widget-body', widget.id);

    content.appendChild(header);
    content.appendChild(body);
    item.appendChild(content);

    header.querySelector('[data-action="config"]').addEventListener('click', () => openConfigDrawer(widget.id));
    header.querySelector('[data-action="refresh"]').addEventListener('click', () => refreshWidget(widget.id));
    header.querySelector('[data-action="delete"]').addEventListener('click', () => removeWidget(widget.id));

    return item;
  }

  function syncLayoutFromGrid() {
    if (!grid) return;
    grid.getGridItems().forEach((el) => {
      const id = el.getAttribute('gs-id');
      const w = findWidget(id);
      if (!w) return;
      const node = el.gridstackNode || {};
      w.layout = {
        x: node.x ?? 0,
        y: node.y ?? 0,
        w: node.w ?? 4,
        h: node.h ?? 2,
      };
    });
    scheduleSave();
  }

  function renderGrid() {
    const container = document.getElementById('dashboard-grid');
    const empty = document.getElementById('dashboard-empty');
    if (!container) return;

    Object.values(chartInstances).forEach((c) => c.dispose());
    chartInstances = {};

    if (grid) {
      grid.destroy(false);
      grid = null;
    }

    container.innerHTML = '';
    const hasWidgets = dashboardState.widgets.length > 0;
    if (empty) empty.classList.toggle('hidden', hasWidgets);

    if (!hasWidgets || typeof GridStack === 'undefined') return;

    grid = GridStack.init({
      column: dashboardState.layout?.columns || 12,
      cellHeight: 80,
      margin: 8,
      float: true,
      disableDrag: !editMode,
      disableResize: !editMode,
      animate: true,
    }, container);

    dashboardState.widgets.forEach((widget) => {
      const el = buildWidgetElement(widget);
      grid.addWidget(el);
      refreshWidget(widget.id);
    });

    grid.on('change', () => syncLayoutFromGrid());
  }

  function addWidget(type) {
    const widget = createWidget(type);
    dashboardState.widgets.push(widget);
    scheduleSave();
    renderGrid();
    if (grid) {
      const el = buildWidgetElement(widget);
      grid.addWidget(el);
      refreshWidget(widget.id);
    }
    openConfigDrawer(widget.id);
  }

  function removeWidget(id) {
    dashboardState.widgets = dashboardState.widgets.filter((w) => w.id !== id);
    if (chartInstances[id]) {
      chartInstances[id].dispose();
      delete chartInstances[id];
    }
    scheduleSave();
    renderGrid();
  }

  async function openConfigDrawer(widgetId) {
    selectedWidgetId = widgetId;
    const widget = findWidget(widgetId);
    const drawer = document.getElementById('dashboard-config-drawer');
    if (!drawer || !widget) return;

    const streams = await fetchStreams();
    const streamOpts = streams.map((s) => `<option value="${s}" ${widget.source?.ref === s ? 'selected' : ''}>${s}</option>`).join('');

    drawer.classList.remove('hidden');
    drawer.innerHTML = `
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-[10px] font-black uppercase tracking-widest text-slate-500">Widget config</h3>
        <button type="button" id="dashboard-config-close" class="text-slate-400 hover:text-slate-900"><span class="material-symbols-outlined text-[18px]">close</span></button>
      </div>
      <label class="block mb-2">
        <span class="text-[9px] font-black uppercase tracking-widest text-slate-400">Title</span>
        <input id="cfg-title" type="text" value="${(widget.title || '').replace(/"/g, '&quot;')}" class="mt-1 w-full rounded-pill border-slate-200 text-[11px] font-mono" />
      </label>
      <label class="block mb-2">
        <span class="text-[9px] font-black uppercase tracking-widest text-slate-400">Stream</span>
        <select id="cfg-stream" class="mt-1 w-full rounded-pill border-slate-200 text-[11px] font-mono">${streamOpts || '<option value="">—</option>'}</select>
      </label>
      <label class="block mb-2">
        <span class="text-[9px] font-black uppercase tracking-widest text-slate-400">X / Category</span>
        <input id="cfg-x" type="text" value="${widget.encoding?.x || ''}" class="mt-1 w-full rounded-pill border-slate-200 text-[11px] font-mono" placeholder="column" />
      </label>
      <label class="block mb-2">
        <span class="text-[9px] font-black uppercase tracking-widest text-slate-400">Y / Value</span>
        <input id="cfg-y" type="text" value="${widget.encoding?.y || ''}" class="mt-1 w-full rounded-pill border-slate-200 text-[11px] font-mono" placeholder="column" />
      </label>
      <label class="block mb-2">
        <span class="text-[9px] font-black uppercase tracking-widest text-slate-400">Aggregation</span>
        <select id="cfg-agg" class="mt-1 w-full rounded-pill border-slate-200 text-[11px] font-mono">
          <option value="sum">Sum</option>
          <option value="avg">Avg</option>
          <option value="count">Count</option>
          <option value="min">Min</option>
          <option value="max">Max</option>
        </select>
      </label>
      <label class="block mb-2">
        <span class="text-[9px] font-black uppercase tracking-widest text-slate-400">Palette</span>
        <select id="cfg-palette" class="mt-1 w-full rounded-pill border-slate-200 text-[11px] font-mono">
          <option value="default">Default</option>
          <option value="emerald">Emerald</option>
          <option value="ocean">Ocean</option>
        </select>
      </label>
      <button type="button" id="cfg-apply" class="w-full mt-4 h-8 rounded-pill bg-primary text-white text-[10px] font-black uppercase tracking-widest shadow-tactile">Apply &amp; Refresh</button>
    `;

    const aggSel = drawer.querySelector('#cfg-agg');
    if (aggSel && widget.transform?.measures?.[0]) {
      aggSel.value = widget.transform.measures[0].agg || 'sum';
    }
    const palSel = drawer.querySelector('#cfg-palette');
    if (palSel) palSel.value = widget.style?.palette || 'default';

    drawer.querySelector('#dashboard-config-close')?.addEventListener('click', () => {
      drawer.classList.add('hidden');
    });
    drawer.querySelector('#cfg-apply')?.addEventListener('click', () => {
      widget.title = drawer.querySelector('#cfg-title')?.value || widget.title;
      widget.source.ref = drawer.querySelector('#cfg-stream')?.value || '';
      widget.encoding.x = drawer.querySelector('#cfg-x')?.value || '';
      widget.encoding.y = drawer.querySelector('#cfg-y')?.value || '';
      const agg = drawer.querySelector('#cfg-agg')?.value || 'sum';
      const yCol = widget.encoding.y;
      if (yCol) {
        widget.transform = widget.transform || {};
        widget.transform.dimensions = widget.encoding.x ? [widget.encoding.x] : [];
        widget.transform.measures = [{ field: yCol, agg }];
        widget.transform.limit = widget.transform.limit || 500;
      }
      widget.style.palette = drawer.querySelector('#cfg-palette')?.value || 'default';
      scheduleSave();
      refreshWidget(widget.id);
      const titleEl = document.querySelector(`[gs-id="${widget.id}"] .font-black`);
      if (titleEl) titleEl.textContent = widget.title;
    });
  }

  function setEditMode(on) {
    editMode = on;
    document.getElementById('dashboard-btn-edit')?.classList.toggle('bg-primary', on);
    document.getElementById('dashboard-btn-edit')?.classList.toggle('text-white', on);
    document.getElementById('dashboard-btn-view')?.classList.toggle('bg-primary', !on);
    document.getElementById('dashboard-btn-view')?.classList.toggle('text-white', !on);
    if (grid) {
      if (typeof grid.setStatic === 'function') {
        grid.setStatic(!on);
      } else if (typeof grid.enableMove === 'function') {
        grid.enableMove(on);
        grid.enableResize(on);
      }
    }
    document.querySelectorAll('.dashboard-widget-actions').forEach((el) => {
      el.classList.toggle('hidden', !on);
    });
  }

  function hydrateDashboard(state) {
    _hydrating = true;
    loadState();
    if (state && typeof state === 'object') {
      dashboardState = { ...defaultDashboard(), ...state, widgets: state.widgets || [] };
    }
    const titleEl = document.getElementById('dashboard-header-name');
    if (titleEl) titleEl.textContent = dashboardState.title || window.SPORE_WORKSPACE?.name || 'Dashboard';
    updateHeader();
    renderGrid();
    _hydrating = false;
  }

  async function registerRelationAfterIngest(streamName, connId, query) {
    const base = typeof window.getWorkspaceApiBase === 'function' ? window.getWorkspaceApiBase() : null;
    if (!base || !streamName) return;
    try {
      await fetch(`${base}/relations/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stream_name: streamName, conn_id: connId, query }),
      });
    } catch (e) {
      console.warn('relation register failed', e);
    }
  }

  function bindPalette() {
    const palette = document.getElementById('dashboard-widget-palette');
    if (!palette) return;
    palette.innerHTML = WIDGET_TYPES.map((t) => `
      <div class="dashboard-palette-item rounded-xl border border-slate-200 p-3 hover:border-primary/40 cursor-pointer transition-colors flex items-center gap-2"
           data-widget-type="${t.type}">
        <span class="material-symbols-outlined text-primary text-[18px]">${t.icon}</span>
        <span class="text-[10px] font-black uppercase tracking-widest text-slate-700">${t.label}</span>
      </div>`).join('');
    palette.querySelectorAll('[data-widget-type]').forEach((el) => {
      el.addEventListener('click', () => addWidget(el.dataset.widgetType));
    });
  }

  function bindControls() {
    document.getElementById('dashboard-btn-add')?.addEventListener('click', () => addWidget('bar'));
    document.getElementById('dashboard-btn-edit')?.addEventListener('click', () => setEditMode(true));
    document.getElementById('dashboard-btn-view')?.addEventListener('click', () => setEditMode(false));
  }

  window.hydrateDashboardFromWorkspace = hydrateDashboard;
  window.registerRelationAfterIngest = registerRelationAfterIngest;
  window.getDashboardState = () => dashboardState;

  document.addEventListener('DOMContentLoaded', () => {
    bindPalette();
    bindControls();
    if (window.SPORE_WORKSPACE_STATE?.dashboard) {
      hydrateDashboard(window.SPORE_WORKSPACE_STATE.dashboard);
    } else {
      hydrateDashboard(null);
    }
  });
})();
