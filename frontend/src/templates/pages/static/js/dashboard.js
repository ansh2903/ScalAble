/**
 * Dashboard: Gridstack + PowerBI-style Visualizations / Field wells / Fields pane.
 */

(function () {
  const PALETTES = {
    default: ['#00A36C', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4'],
    emerald: ['#00A36C', '#065f46', '#34d399', '#6ee7b7'],
    ocean: ['#0ea5e9', '#0284c7', '#0369a1', '#075985'],
  };

  const AGG_OPTIONS = [
    { value: 'sum', label: 'Sum' },
    { value: 'avg', label: 'Avg' },
    { value: 'count', label: 'Count' },
    { value: 'count_distinct', label: 'Count Distinct' },
    { value: 'min', label: 'Min' },
    { value: 'max', label: 'Max' },
  ];

  const CART_TYPES = ['bar', 'line', 'area', 'map', 'radar', 'treemap'];

  // Widget types that can publish a selection onto the dashboard filter bus.
  const CLICK_FILTER_TYPES = ['bar', 'line', 'area', 'pie', 'map', 'funnel', 'treemap'];

  // Widget types rendered with ECharts (eligible for PNG snapshot export).
  const CHART_TYPES = ['bar', 'line', 'area', 'pie', 'scatter', 'heatmap', 'radar', 'funnel', 'gauge', 'treemap', 'map'];

  // Choropleth scopes. World/USA/India ship bundled under /static/js/vendor
  // (offline-safe). Other countries load on demand from the internet — `ne`
  // filters the Natural Earth admin-1 dataset (fetched once, cached); `ch`
  // pulls a per-country file from click_that_hood. `region` controls how raw
  // values are normalized to match the feature names.
  const MAP_SCOPES = {
    world: { label: 'World countries', mapName: 'world', file: 'world.json', region: 'country',
      urls: ['https://fastly.jsdelivr.net/npm/echarts@4.9.0/map/json/world.json',
             'https://cdn.jsdelivr.net/npm/echarts@4.9.0/map/json/world.json'] },
    usa: { label: 'United States (states)', mapName: 'USA', file: 'usa.json', region: 'state',
      urls: ['https://fastly.jsdelivr.net/npm/echarts@4.9.0/map/json/usa.json',
             'https://cdn.jsdelivr.net/npm/echarts@4.9.0/map/json/usa.json'] },
    india: { label: 'India (states)', mapName: 'india', file: 'india.json', region: 'plain' },
    china: { label: 'China (provinces)', mapName: 'china', region: 'plain', ne: 'China' },
    brazil: { label: 'Brazil (states)', mapName: 'brazil', region: 'plain', ne: 'Brazil' },
    canada: { label: 'Canada (provinces)', mapName: 'canada', region: 'plain', ne: 'Canada' },
    australia: { label: 'Australia (states)', mapName: 'australia', region: 'plain', ne: 'Australia' },
    russia: { label: 'Russia (regions)', mapName: 'russia', region: 'plain', ne: 'Russia' },
    indonesia: { label: 'Indonesia (provinces)', mapName: 'indonesia', region: 'plain', ne: 'Indonesia' },
    'south-africa': { label: 'South Africa (provinces)', mapName: 'south-africa', region: 'plain', ne: 'South Africa' },
    germany: { label: 'Germany (states)', mapName: 'germany', region: 'plain', ch: 'germany' },
    uk: { label: 'United Kingdom (regions)', mapName: 'uk', region: 'plain', ch: 'united-kingdom' },
    japan: { label: 'Japan (prefectures)', mapName: 'japan', region: 'plain', ch: 'japan', nameKey: 'name_english' },
  };

  const VENDOR_MAP_BASE = '/static/js/vendor/';
  const NE_ADMIN1_URL = 'https://cdn.jsdelivr.net/gh/nvkelso/natural-earth-vector@master/geojson/ne_50m_admin_1_states_provinces.geojson';
  const CLICK_THAT_HOOD_BASE = 'https://cdn.jsdelivr.net/gh/codeforgermany/click_that_hood@main/public/data/';

  function mapScopeDef(scope) {
    return MAP_SCOPES[scope] || MAP_SCOPES.world;
  }

  let _neAdmin1Promise = null;
  // Natural Earth admin-1 GeoJSON for all countries (one ~2 MB fetch, cached).
  function loadNaturalEarthAdmin1() {
    if (_neAdmin1Promise) return _neAdmin1Promise;
    _neAdmin1Promise = (async () => {
      const res = await fetch(NE_ADMIN1_URL);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    })().catch((e) => {
      _neAdmin1Promise = null;
      throw e;
    });
    return _neAdmin1Promise;
  }

  // Register a single scope's GeoJSON with ECharts, choosing the right source.
  async function registerScopeMap(def) {
    if (def.ne) {
      const ne = await loadNaturalEarthAdmin1();
      const features = (ne.features || [])
        .filter((f) => f.properties && f.properties.admin === def.ne)
        .map((f) => ({ type: 'Feature', properties: { name: f.properties.name }, geometry: f.geometry }));
      if (!features.length) throw new Error(`No regions for ${def.label}`);
      echarts.registerMap(def.mapName, { type: 'FeatureCollection', features });
      return;
    }
    if (def.ch) {
      const res = await fetch(CLICK_THAT_HOOD_BASE + def.ch + '.geojson');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const geo = await res.json();
      if (def.nameKey) {
        (geo.features || []).forEach((f) => {
          if (f.properties && f.properties[def.nameKey]) f.properties.name = f.properties[def.nameKey];
        });
      }
      echarts.registerMap(def.mapName, geo);
      return;
    }
    // Bundled scope: local file first, then any CDN fallbacks.
    const urls = [VENDOR_MAP_BASE + def.file, ...(def.urls || [])];
    let lastErr = null;
    for (const url of urls) {
      try {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        echarts.registerMap(def.mapName, await res.json());
        return;
      } catch (e) {
        lastErr = e;
      }
    }
    throw lastErr || new Error(`Could not load ${def.label} map data`);
  }

  const STATE_ALIASES = {
    al: 'Alabama', ak: 'Alaska', az: 'Arizona', ar: 'Arkansas', ca: 'California',
    co: 'Colorado', ct: 'Connecticut', de: 'Delaware', fl: 'Florida', ga: 'Georgia',
    hi: 'Hawaii', id: 'Idaho', il: 'Illinois', in: 'Indiana', ia: 'Iowa',
    ks: 'Kansas', ky: 'Kentucky', la: 'Louisiana', me: 'Maine', md: 'Maryland',
    ma: 'Massachusetts', mi: 'Michigan', mn: 'Minnesota', ms: 'Mississippi', mo: 'Missouri',
    mt: 'Montana', ne: 'Nebraska', nv: 'Nevada', nh: 'New Hampshire', nj: 'New Jersey',
    nm: 'New Mexico', ny: 'New York', nc: 'North Carolina', nd: 'North Dakota', oh: 'Ohio',
    ok: 'Oklahoma', or: 'Oregon', pa: 'Pennsylvania', ri: 'Rhode Island', sc: 'South Carolina',
    sd: 'South Dakota', tn: 'Tennessee', tx: 'Texas', ut: 'Utah', vt: 'Vermont',
    va: 'Virginia', wa: 'Washington', wv: 'West Virginia', wi: 'Wisconsin', wy: 'Wyoming',
    dc: 'District of Columbia',
  };

  // Common country-name aliases mapped to the names used by the world GeoJSON.
  const COUNTRY_ALIASES = {
    'usa': 'United States',
    'us': 'United States',
    'u.s.': 'United States',
    'u.s.a.': 'United States',
    'united states of america': 'United States',
    'uk': 'United Kingdom',
    'u.k.': 'United Kingdom',
    'great britain': 'United Kingdom',
    'russian federation': 'Russia',
    'south korea': 'Korea',
    'republic of korea': 'Korea',
    'korea, south': 'Korea',
    'north korea': 'Dem. Rep. Korea',
    'czech republic': 'Czech Rep.',
    'czechia': 'Czech Rep.',
    'uae': 'United Arab Emirates',
    'drc': 'Dem. Rep. Congo',
    'democratic republic of the congo': 'Dem. Rep. Congo',
    'republic of the congo': 'Congo',
    'ivory coast': "Côte d'Ivoire",
    'myanmar': 'Myanmar',
    'burma': 'Myanmar',
    'vietnam': 'Vietnam',
    'laos': 'Lao PDR',
    'syria': 'Syria',
    'iran': 'Iran',
    'venezuela': 'Venezuela',
    'tanzania': 'Tanzania',
    'bolivia': 'Bolivia',
    'moldova': 'Moldova',
    'macedonia': 'Macedonia',
    'bosnia and herzegovina': 'Bosnia and Herz.',
    'dominican republic': 'Dominican Rep.',
    'central african republic': 'Central African Rep.',
    'south sudan': 'S. Sudan',
    'equatorial guinea': 'Eq. Guinea',
    'solomon islands': 'Solomon Is.',
  };

  const FILTER_OPS = [
    { value: 'eq', label: '=' },
    { value: 'neq', label: '≠' },
    { value: 'gt', label: '>' },
    { value: 'gte', label: '≥' },
    { value: 'lt', label: '<' },
    { value: 'lte', label: '≤' },
    { value: 'contains', label: 'contains' },
  ];

  const WIDGET_TYPES = [
    { type: 'bar', icon: 'bar_chart', label: 'Bar' },
    { type: 'line', icon: 'show_chart', label: 'Line' },
    { type: 'area', icon: 'area_chart', label: 'Area' },
    { type: 'pie', icon: 'pie_chart', label: 'Pie' },
    { type: 'scatter', icon: 'scatter_plot', label: 'Scatter' },
    { type: 'heatmap', icon: 'grid_on', label: 'Heatmap' },
    { type: 'radar', icon: 'radar', label: 'Radar' },
    { type: 'funnel', icon: 'details', label: 'Funnel' },
    { type: 'gauge', icon: 'speed', label: 'Gauge' },
    { type: 'treemap', icon: 'grid_view', label: 'Treemap' },
    { type: 'kpi', icon: 'pin', label: 'KPI' },
    { type: 'table', icon: 'table_chart', label: 'Table' },
    { type: 'map', icon: 'public', label: 'World Map' },
    { type: 'slicer', icon: 'filter_alt', label: 'Slicer' },
    { type: 'parameter', icon: 'tune', label: 'Parameter' },
    { type: 'button', icon: 'smart_button', label: 'Button' },
    { type: 'text', icon: 'notes', label: 'Text' },
  ];

  const WIDGET_REGISTRY = {
    bar: {
      wells: [
        { id: 'axis', label: 'Axis', role: 'dimension', max: 1 },
        { id: 'legend', label: 'Legend', role: 'dimension', max: 1 },
        { id: 'values', label: 'Values', role: 'measure', max: Infinity },
        { id: 'tooltips', label: 'Tooltips', role: 'measure', max: Infinity },
      ],
    },
    line: {
      wells: [
        { id: 'axis', label: 'Axis', role: 'dimension', max: 1 },
        { id: 'legend', label: 'Legend', role: 'dimension', max: 1 },
        { id: 'values', label: 'Values', role: 'measure', max: Infinity },
        { id: 'tooltips', label: 'Tooltips', role: 'measure', max: Infinity },
      ],
    },
    area: {
      wells: [
        { id: 'axis', label: 'Axis', role: 'dimension', max: 1 },
        { id: 'legend', label: 'Legend', role: 'dimension', max: 1 },
        { id: 'values', label: 'Values', role: 'measure', max: Infinity },
        { id: 'tooltips', label: 'Tooltips', role: 'measure', max: Infinity },
      ],
    },
    pie: {
      wells: [
        { id: 'legend', label: 'Legend', role: 'dimension', max: 1 },
        { id: 'values', label: 'Values', role: 'measure', max: 1 },
      ],
    },
    scatter: {
      wells: [
        { id: 'xValues', label: 'X Values', role: 'measure', max: 1 },
        { id: 'yValues', label: 'Y Values', role: 'measure', max: 1 },
        { id: 'size', label: 'Size', role: 'measure', max: 1 },
        { id: 'legend', label: 'Legend', role: 'dimension', max: 1 },
        { id: 'details', label: 'Details', role: 'dimension', max: 1 },
      ],
    },
    heatmap: {
      wells: [
        { id: 'rows', label: 'Rows', role: 'dimension', max: 1 },
        { id: 'columns', label: 'Columns', role: 'dimension', max: 1 },
        { id: 'values', label: 'Values', role: 'measure', max: 1 },
      ],
    },
    radar: {
      wells: [
        { id: 'axis', label: 'Indicators', role: 'dimension', max: 1 },
        { id: 'legend', label: 'Legend', role: 'dimension', max: 1 },
        { id: 'values', label: 'Values', role: 'measure', max: Infinity },
      ],
    },
    funnel: {
      wells: [
        { id: 'axis', label: 'Stage', role: 'dimension', max: 1 },
        { id: 'values', label: 'Values', role: 'measure', max: 1 },
      ],
    },
    gauge: {
      wells: [{ id: 'value', label: 'Value', role: 'measure', max: 1 }],
    },
    treemap: {
      wells: [
        { id: 'axis', label: 'Category', role: 'dimension', max: 1 },
        { id: 'legend', label: 'Group', role: 'dimension', max: 1 },
        { id: 'values', label: 'Values', role: 'measure', max: 1 },
      ],
    },
    kpi: {
      wells: [{ id: 'fields', label: 'Fields', role: 'measure', max: 1 }],
    },
    table: {
      wells: [{ id: 'columns', label: 'Columns', role: 'dimension', max: Infinity }],
    },
    slicer: {
      wells: [{ id: 'field', label: 'Field', role: 'dimension', max: 1 }],
    },
    map: {
      wells: [
        { id: 'axis', label: 'Location', role: 'dimension', max: 1 },
        { id: 'values', label: 'Values', role: 'measure', max: 1 },
      ],
    },
    parameter: {
      wells: [],
      noData: true,
    },
    button: {
      wells: [],
      noData: true,
    },
    text: {
      wells: [],
      noData: true,
    },
  };

  let dashboardState = { title: '', pages: [], activePageId: null, metadata: {} };
  let grid = null;
  let chartInstances = {};
  // Transient cross-widget filter bus: controllerWidgetId -> { field, op, value }.
  let dashboardFilters = {};
  // What-if parameter bus: paramName -> current slider value.
  let dashboardParams = {};
  let editMode = true;
  let selectedWidgetId = null;
  let relationsCache = {};
  let datasetsCache = {};
  let _hydrating = false;
  let _saveTimer = null;
  let _dragField = null;

  function getRegistry(type) {
    return WIDGET_REGISTRY[type] || WIDGET_REGISTRY.bar;
  }

  function isChartWidgetType(type) {
    return CHART_TYPES.includes((type || '').toLowerCase());
  }

  let _toastTimer = null;
  function showToast(message, variant = 'info') {
    let el = document.getElementById('dashboard-toast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'dashboard-toast';
      el.className = 'fixed bottom-6 left-1/2 -translate-x-1/2 z-[9999] px-4 py-2 rounded-pill text-[11px] font-bold shadow-lg pointer-events-none opacity-0 transition-opacity duration-300';
      document.body.appendChild(el);
    }
    const styles = {
      info: 'bg-slate-900 text-white',
      error: 'bg-red-600 text-white',
      success: 'bg-primary text-white',
    };
    el.className = `fixed bottom-6 left-1/2 -translate-x-1/2 z-[9999] px-4 py-2 rounded-pill text-[11px] font-bold shadow-lg pointer-events-none transition-opacity duration-300 ${styles[variant] || styles.info}`;
    el.textContent = message;
    el.style.opacity = '1';
    if (_toastTimer) clearTimeout(_toastTimer);
    _toastTimer = setTimeout(() => { el.style.opacity = '0'; }, 2600);
  }

  function dataUrlToBlob(dataUrl) {
    const [header, b64] = dataUrl.split(',');
    const mime = (header.match(/:(.*?);/) || [])[1] || 'image/png';
    const bin = atob(b64);
    const arr = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    return new Blob([arr], { type: mime });
  }

  function downloadDataUrl(dataUrl, filename) {
    const a = document.createElement('a');
    a.href = dataUrl;
    a.download = filename;
    a.click();
  }

  async function snapshotWidgetPng(widgetId) {
    const widget = findWidget(widgetId);
    const inst = chartInstances[widgetId];
    if (!widget || !inst) {
      showToast('Chart not ready yet', 'error');
      return;
    }
    try {
      const url = inst.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#ffffff' });
      const blob = dataUrlToBlob(url);
      const safeName = (widget.title || widget.type || 'chart').replace(/[^\w\-]+/g, '_').slice(0, 48);
      if (navigator.clipboard?.write && window.ClipboardItem) {
        try {
          await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
          showToast('Chart copied to clipboard', 'success');
          return;
        } catch (_) { /* fall through to download */ }
      }
      downloadDataUrl(url, `${safeName}.png`);
      showToast('Chart downloaded as PNG', 'success');
    } catch (e) {
      console.warn('snapshot failed', e);
      showToast('Could not export chart', 'error');
    }
  }

  function exportDashboardHtml() {
    const id = typeof window.getActiveWorkspaceId === 'function' ? window.getActiveWorkspaceId() : null;
    if (!id) {
      showToast('No active workspace', 'error');
      return;
    }
    window.location.href = `/api/workspaces/${encodeURIComponent(id)}/dashboard/export`;
  }

  // Load a UMD bundle as a browser global. An AMD loader (Monaco's
  // loader.min.js) defines a global `define.amd`, which would otherwise make
  // these UMD files register as anonymous AMD modules instead of attaching to
  // `window`. We temporarily neutralize `define` around the load so they take
  // the plain-browser path, then restore it.
  function loadScriptOnce(src, globalName) {
    if (window[globalName]) return Promise.resolve(window[globalName]);
    return new Promise((resolve, reject) => {
      const savedDefine = window.define;
      const amdActive = typeof savedDefine === 'function' && savedDefine.amd;
      if (amdActive) window.define = undefined;
      const restore = () => { if (amdActive) window.define = savedDefine; };
      const s = document.createElement('script');
      s.src = src;
      s.onload = () => { restore(); resolve(window[globalName]); };
      s.onerror = () => { restore(); reject(new Error(`Could not load ${src}`)); };
      document.head.appendChild(s);
    });
  }

  // Sequential (not parallel) so the temporary `define` neutralization in
  // loadScriptOnce never overlaps between the two bundles.
  async function ensurePdfLibraries() {
    await loadScriptOnce('/static/js/vendor/html2canvas.min.js', 'html2canvas');
    await loadScriptOnce('/static/js/vendor/jspdf.umd.min.js', 'jspdf');
    return {
      html2canvasLib: window.html2canvas,
      jsPdfLib: window.jspdf,
    };
  }

  async function waitForChartsReady(pageWidgets) {
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    Object.values(chartInstances).forEach((c) => {
      try { c.resize(); } catch (_) { /* noop */ }
    });
    const hasMap = (pageWidgets || []).some((w) => (w.type || '').toLowerCase() === 'map');
    await new Promise((r) => setTimeout(r, hasMap ? 900 : 200));
  }

  async function exportDashboardPdf() {
    const gridEl = document.getElementById('dashboard-grid');
    if (!gridEl) return;

    const pages = dashboardState.pages || [];
    if (!pages.length) {
      showToast('Nothing to export', 'error');
      return;
    }

    const origPageId = dashboardState.activePageId;
    showToast('Generating PDF…');

    try {
      const { html2canvasLib, jsPdfLib } = await ensurePdfLibraries();
      if (!html2canvasLib || !jsPdfLib?.jsPDF) {
        showToast('PDF libraries not loaded', 'error');
        return;
      }

      const pdf = new jsPdfLib.jsPDF({ orientation: 'landscape', unit: 'pt', format: 'a4' });
      const pageW = pdf.internal.pageSize.getWidth();
      const pageH = pdf.internal.pageSize.getHeight();
      const margin = 28;
      const titleH = 18;

      for (let i = 0; i < pages.length; i++) {
        const page = pages[i];
        dashboardState.activePageId = page.id;
        renderGrid();
        await waitForChartsReady(page.widgets || []);

        const canvas = await html2canvasLib(gridEl, {
          scale: 2,
          backgroundColor: '#f8fafc',
          useCORS: true,
          logging: false,
        });
        const imgData = canvas.toDataURL('image/png');
        let imgW = pageW - margin * 2;
        let imgH = (canvas.height / canvas.width) * imgW;
        const maxH = pageH - margin * 2 - titleH;
        if (imgH > maxH) {
          imgH = maxH;
          imgW = (canvas.width / canvas.height) * imgH;
        }
        const x = (pageW - imgW) / 2;
        const y = margin + titleH;

        if (i > 0) pdf.addPage();
        pdf.setFontSize(11);
        pdf.setTextColor(80);
        pdf.text(page.name || `Page ${i + 1}`, margin, margin + 10);
        pdf.addImage(imgData, 'PNG', x, y, imgW, imgH);
      }

      dashboardState.activePageId = origPageId;
      renderGrid();

      const name = (dashboardState.title || window.SPORE_WORKSPACE?.name || 'dashboard')
        .replace(/[^\w\-]+/g, '_')
        .slice(0, 64);
      pdf.save(`${name}.pdf`);
      showToast('PDF downloaded', 'success');
    } catch (e) {
      console.warn('PDF export failed', e);
      dashboardState.activePageId = origPageId;
      renderGrid();
      showToast('PDF export failed', 'error');
    }
  }

  function toggleExportDropdown(force) {
    const menu = document.getElementById('dashboard-export-dropdown');
    if (!menu) return;
    const open = force !== undefined ? force : menu.classList.contains('hidden');
    menu.classList.toggle('hidden', !open);
  }

  function widgetNoData(type) {
    return !!getRegistry(type).noData;
  }

  function resolveQueryColumns(widget, columns) {
    const dimCount = (widget.transform?.dimensions || []).length;
    return {
      dimCols: columns.slice(0, dimCount),
      measureCols: columns.slice(dimCount),
    };
  }

  function chartConfigHint(widget) {
    const w = widget.wells || {};
    const type = widget.type || 'bar';
    if (type === 'pie') {
      if (!wellField(w.legend, 0) || !wellField(w.values, 0)) {
        return 'Add Legend (category) and Values (measure) in the wells.';
      }
    } else if (type === 'heatmap') {
      if (!wellField(w.rows, 0) || !wellField(w.columns, 0) || !wellField(w.values, 0)) {
        return 'Add Rows, Columns, and Values in the wells.';
      }
    } else if (type === 'funnel') {
      if (!wellField(w.axis, 0) || !wellField(w.values, 0)) {
        return 'Add Stage (category) and a Values (measure) field.';
      }
    } else if (type === 'gauge') {
      if (!wellField(w.value, 0)) return 'Add a measure to the Value well.';
    } else if (type === 'kpi') {
      if (!wellField(w.fields, 0)) return 'Add a field to the Fields well.';
    } else if (type === 'slicer') {
      if (!wellField(w.field, 0)) return 'Add a field to slice the dashboard by.';
    } else if (CART_TYPES.includes(type)) {
      if (!wellField(w.axis, 0) || !(w.values || []).length) {
        return 'Add Axis (category) and at least one Values field.';
      }
    } else if (type === 'scatter') {
      if (!wellField(w.xValues, 0) || !wellField(w.yValues, 0)) {
        return 'Add X Values and Y Values in the wells.';
      }
    }
    return null;
  }

  function genPageId() {
    return `p_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`;
  }

  // Normalize any saved dashboard (legacy single-page or multi-page) into the
  // pages[] model. Legacy state used a top-level `widgets`/`layout`; wrap it as
  // the first page so old dashboards keep working.
  function ensurePages(state) {
    const s = state && typeof state === 'object' ? state : {};
    let pages = Array.isArray(s.pages) && s.pages.length ? s.pages : null;
    if (!pages) {
      pages = [{
        id: genPageId(),
        name: 'Page 1',
        widgets: Array.isArray(s.widgets) ? s.widgets : [],
        layout: s.layout || { columns: 12 },
      }];
    }
    pages = pages.map((p, i) => {
      const widgets = Array.isArray(p.widgets) ? p.widgets.map((w) => ensureWidget({ ...w })) : [];
      let activeSource = p.activeSource || '';
      if (!activeSource && widgets.length) {
        const refs = widgets.map((w) => w.source?.ref).filter(Boolean);
        const uniq = [...new Set(refs)];
        if (uniq.length === 1) activeSource = uniq[0];
      }
      if (activeSource) {
        widgets.forEach((w) => {
          if (!widgetNoData(w.type)) {
            if (!w.source) w.source = { kind: 'stream', ref: '' };
            if (!w.source.ref) w.source.ref = activeSource;
          }
        });
      }
      return {
        id: p.id || genPageId(),
        name: p.name || `Page ${i + 1}`,
        widgets,
        layout: p.layout || { columns: 12 },
        activeSource,
      };
    });
    let activePageId = s.activePageId;
    if (!pages.some((p) => p.id === activePageId)) activePageId = pages[0].id;
    return {
      title: s.title || window.SPORE_WORKSPACE?.name || 'Dashboard',
      pages,
      activePageId,
      metadata: s.metadata || {},
    };
  }

  function defaultDashboard() {
    return ensurePages({});
  }

  function currentPage() {
    const pages = dashboardState.pages || [];
    let p = pages.find((x) => x.id === dashboardState.activePageId);
    if (!p && pages.length) {
      p = pages[0];
      dashboardState.activePageId = p.id;
    }
    return p || null;
  }

  function currentWidgets() {
    const p = currentPage();
    return p ? p.widgets : [];
  }

  function emptyWells(type) {
    const wells = {};
    (getRegistry(type).wells || []).forEach((w) => {
      wells[w.id] = [];
    });
    return wells;
  }

  function wellField(arr, idx) {
    const item = arr?.[idx];
    if (!item) return '';
    return typeof item === 'string' ? item : item.field;
  }

  function chipAgg(arr, idx) {
    const item = arr?.[idx];
    if (!item || typeof item === 'string') return 'sum';
    return item.agg || 'sum';
  }

  function isNumericType(dtype) {
    const t = String(dtype || '').toUpperCase();
    return /INT|FLOAT|DOUBLE|DECIMAL|NUMERIC|REAL|BIGINT|SMALLINT|TINYINT|HUGEINT/.test(t);
  }

  function defaultAggForField(fieldName, schema) {
    if (fieldName === '*') return 'count';
    const col = (schema || []).find((s) => s.name === fieldName);
    return isNumericType(col?.type) ? 'sum' : 'count';
  }

  function chipDisplayLabel(field) {
    return field === '*' ? 'Count of rows' : field;
  }

  function buildMeasures(schema, q) {
    const measures = [];
    const ql = (q || '').toLowerCase();
    const countLabel = 'Count of rows';
    if (!ql || countLabel.toLowerCase().includes(ql) || ql.includes('count')) {
      measures.push({ field: '*', dtype: '*', agg: 'count', label: countLabel });
    }
    (schema || []).forEach((col) => {
      if (!isNumericType(col.type)) return;
      const label = `Sum of ${col.name}`;
      if (ql && !label.toLowerCase().includes(ql) && !col.name.toLowerCase().includes(ql)) return;
      measures.push({ field: col.name, dtype: col.type, agg: 'sum', label });
    });
    return measures;
  }

  function measureWellForWidget(widget) {
    if (!widget || widgetNoData(widget.type)) return null;
    const reg = getRegistry(widget.type);
    if (reg.wells.some((w) => w.id === 'values' && w.role === 'measure')) return 'values';
    if (reg.wells.some((w) => w.id === 'fields' && w.role === 'measure')) return 'fields';
    const meas = reg.wells.find((w) => w.role === 'measure');
    return meas ? meas.id : null;
  }

  function addMeasure(widget, field, agg) {
    const wellId = measureWellForWidget(widget);
    if (!wellId) return false;
    return addChipToWell(widget, wellId, { field, agg });
  }

  function migrateLegacyWidget(widget) {
    if (widget.wells && Object.keys(widget.wells).length) return widget;
    // No-data widgets (text, button) have no wells. Returning here avoids the
    // mapWellsToQuery → ensureWidget → migrateLegacyWidget recursion, since their
    // emptyWells() is {} and would never satisfy the guard above.
    if (widgetNoData(widget.type)) {
      if (!widget.wells) widget.wells = {};
      return widget;
    }
    const enc = widget.encoding || {};
    const tr = widget.transform || {};
    const wells = emptyWells(widget.type || 'bar');
    const type = widget.type || 'bar';

    if (CART_TYPES.includes(type) || type === 'pie') {
      if (enc.x) wells.axis = [{ field: enc.x }];
      if (enc.series) wells.legend = [{ field: enc.series }];
      else if (type === 'pie' && enc.x) wells.legend = [{ field: enc.x }];
      const y = enc.y || tr.measures?.[0]?.field;
      if (y) {
        wells.values = [{ field: y, agg: tr.measures?.[0]?.agg || 'sum' }];
      }
    } else if (type === 'kpi') {
      const y = enc.y || tr.measures?.[0]?.field;
      if (y) wells.fields = [{ field: y, agg: tr.measures?.[0]?.agg || 'sum' }];
    } else if (type === 'scatter') {
      if (enc.x) wells.xValues = [{ field: enc.x }];
      if (enc.y) wells.yValues = [{ field: enc.y }];
      if (enc.series) wells.legend = [{ field: enc.series }];
    } else if (type === 'heatmap') {
      if (enc.y) wells.rows = [{ field: enc.y }];
      if (enc.x) wells.columns = [{ field: enc.x }];
      if (enc.z) wells.values = [{ field: enc.z, agg: 'sum' }];
    } else if (type === 'table' && enc.columns) {
      wells.columns = enc.columns.map((f) => ({ field: f }));
    }

    widget.wells = wells;
    mapWellsToQuery(widget);
    return widget;
  }

  function ensureWidget(widget) {
    migrateLegacyWidget(widget);
    if (!widget.wells) widget.wells = emptyWells(widget.type);
    if (!widget.source) widget.source = { kind: 'stream', ref: '' };
    if (!widget.style) widget.style = { palette: 'default', showLegend: true };
    if (!widget.transform) widget.transform = { dimensions: [], measures: [], limit: 500 };
    if (!widget.encoding) widget.encoding = {};
    if (!Array.isArray(widget.filters)) widget.filters = [];
    if (!widget.sort || typeof widget.sort !== 'object') widget.sort = {};
    if (!Array.isArray(widget.respondsTo)) widget.respondsTo = [];
    if (widget.type === 'button' && (!widget.nav || typeof widget.nav !== 'object')) {
      widget.nav = { target: '' };
    }
    if (widget.type === 'parameter') {
      if (!widget.param || typeof widget.param !== 'object') {
        widget.param = { name: 'param1', min: 0, max: 100, step: 1, value: 10 };
      }
    }
    if (widget.type === 'table' && !widget.style.table) {
      widget.style.table = { groupBy: '', dataBars: [], rules: [] };
    }
    if (widget.type === 'kpi' && !widget.style.kpi) {
      widget.style.kpi = { target: '', targetColumn: '', format: 'currency', goodDirection: 'up', showDelta: true };
    } else if (widget.type === 'kpi' && widget.style.kpi && !widget.style.kpi.format) {
      widget.style.kpi.format = 'currency';
    }
    if (widget.type === 'map' && !widget.style.mapScope) {
      widget.style.mapScope = 'world';
    }
    return widget;
  }

  function chipsFromWell(wellArr) {
    return (wellArr || []).map((c) =>
      typeof c === 'string' ? { field: c, agg: 'sum' } : { field: c.field, agg: c.agg || 'sum' }
    );
  }

  function widgetOrderBy(widget) {
    const f = widget.sort?.field;
    if (!f) return [];
    return [{ field: f, dir: widget.sort.dir === 'desc' ? 'desc' : 'asc' }];
  }

  function widgetBaseFilters(widget) {
    return (widget.filters || [])
      .filter((f) => f && f.field && f.op)
      .map((f) => ({ field: f.field, op: f.op, value: f.value }));
  }

  function mapWellsToQuery(widget) {
    ensureWidget(widget);
    if (widgetNoData(widget.type)) return;
    const w = widget.wells;
    const type = widget.type || 'bar';
    let limit = widget.transform?.limit || 500;

    if (limit === 1 && type !== 'kpi') limit = 500;

    const base = { filters: widgetBaseFilters(widget), orderBy: widgetOrderBy(widget) };

    if (type === 'scatter') {
      widget.encoding = {
        x: wellField(w.xValues, 0),
        y: wellField(w.yValues, 0),
        size: wellField(w.size, 0),
        series: wellField(w.legend, 0),
        detail: wellField(w.details, 0),
      };
      widget.transform = { dimensions: [], measures: [], limit, ...base };
      return;
    }

    if (type === 'kpi') {
      const f = wellField(w.fields, 0);
      widget.encoding = { y: f };
      widget.transform = {
        dimensions: [],
        measures: f ? [{ field: f, agg: chipAgg(w.fields, 0) }] : [],
        limit: 1,
        ...base,
      };
      return;
    }

    if (type === 'slicer') {
      const f = wellField(w.field, 0);
      widget.encoding = { x: f };
      widget.transform = {
        dimensions: f ? [f] : [],
        measures: [],
        limit: Math.min(limit, 1000),
        ...base,
      };
      return;
    }

    if (type === 'heatmap') {
      const rowF = wellField(w.rows, 0);
      const colF = wellField(w.columns, 0);
      const valF = wellField(w.values, 0);
      widget.encoding = { x: colF, y: rowF, z: valF };
      widget.transform = {
        dimensions: [rowF, colF].filter(Boolean),
        measures: valF ? [{ field: valF, agg: chipAgg(w.values, 0) }] : [],
        limit,
        ...base,
      };
      return;
    }

    if (type === 'table') {
      const cols = chipsFromWell(w.columns).map((c) => c.field);
      widget.encoding = { columns: cols };
      widget.transform = { dimensions: [], measures: [], limit, ...base };
      return;
    }

    if (type === 'pie') {
      const leg = wellField(w.legend, 0);
      const val = wellField(w.values, 0);
      widget.encoding = { x: leg, y: val };
      widget.transform = {
        dimensions: leg ? [leg] : [],
        measures: val ? [{ field: val, agg: chipAgg(w.values, 0) }] : [],
        limit,
        ...base,
      };
      return;
    }

    if (type === 'map') {
      const axis = wellField(w.axis, 0);
      const val = wellField(w.values, 0);
      widget.encoding = { x: axis, y: val };
      widget.transform = {
        dimensions: axis ? [axis] : [],
        measures: val ? [{ field: val, agg: chipAgg(w.values, 0) }] : [],
        limit,
        ...base,
      };
      return;
    }

    if (type === 'funnel') {
      const stage = wellField(w.axis, 0);
      const val = wellField(w.values, 0);
      widget.encoding = { x: stage, y: val };
      widget.transform = {
        dimensions: stage ? [stage] : [],
        measures: val ? [{ field: val, agg: chipAgg(w.values, 0) }] : [],
        limit,
        ...base,
      };
      return;
    }

    if (type === 'gauge') {
      const f = wellField(w.value, 0);
      widget.encoding = { y: f };
      widget.transform = {
        dimensions: [],
        measures: f ? [{ field: f, agg: chipAgg(w.value, 0) }] : [],
        limit: 1,
        ...base,
      };
      return;
    }

    const axis = wellField(w.axis, 0);
    let legend = wellField(w.legend, 0);
    if (legend && legend === axis) legend = '';
    const valueChips = chipsFromWell(w.values);
    widget.encoding = {
      x: axis,
      series: legend,
      y: valueChips[0]?.field || '',
      measures: valueChips.map((c) => c.field),
    };
    const dims = [axis, legend].filter(Boolean);
    widget.transform = {
      dimensions: dims,
      measures: valueChips.map((c) => ({ field: c.field, agg: c.agg })),
      limit,
      ...base,
    };
  }

  function loadState() {
    if (typeof window.getWorkspaceDashboardState === 'function') {
      const s = window.getWorkspaceDashboardState();
      if (s && typeof s === 'object') {
        dashboardState = ensurePages(s);
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
    if (countEl) countEl.textContent = String(currentWidgets().length);
  }

  function genId() {
    return `w_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
  }

  function findWidget(id) {
    return currentWidgets().find((w) => w.id === id);
  }

  function nextLayoutSlot() {
    let maxY = 0;
    currentWidgets().forEach((w) => {
      const ly = (w.layout?.y || 0) + (w.layout?.h || 2);
      if (ly > maxY) maxY = ly;
    });
    return { x: 0, y: maxY, w: 6, h: 2 };
  }

  function createWidget(type) {
    const t = type || 'bar';
    const layout = nextLayoutSlot();
    if (t === 'text') {
      layout.h = 4;
      layout.w = 4;
    } else if (t === 'button') {
      layout.h = 1;
      layout.w = 2;
    } else if (t === 'parameter') {
      layout.h = 1;
      layout.w = 3;
    } else if (t === 'kpi') {
      layout.h = 2;
      layout.w = 3;
    } else {
      layout.h = 4;
    }
    return ensureWidget({
      id: genId(),
      type: t,
      title: t === 'button' ? 'Go to page' : t === 'parameter' ? 'What-if' : `${t.charAt(0).toUpperCase()}${t.slice(1)}`,
      source: { kind: 'stream', ref: pageSourceRef() },
      wells: emptyWells(t),
      text: t === 'text' ? '### Text\nEdit content in the **Formatting** panel on the right.' : undefined,
      nav: t === 'button' ? { target: '' } : undefined,
      param: t === 'parameter' ? { name: `param_${Date.now().toString(36).slice(-4)}`, min: 0, max: 100, step: 1, value: 10 } : undefined,
      transform: { dimensions: [], measures: [], limit: 500 },
      encoding: {},
      filters: [],
      sort: {},
      respondsTo: [],
      style: {
        palette: 'default',
        showLegend: true,
        ...(t === 'table' ? { table: { groupBy: '', dataBars: [], rules: [] } } : {}),
        ...(t === 'kpi' ? { kpi: { target: '', targetColumn: '', format: 'currency', goodDirection: 'up', showDelta: true } } : {}),
        ...(t === 'map' ? { mapScope: 'world' } : {}),
      },
      layout,
    });
  }

  async function fetchDatasets() {
    try {
      const res = await fetch('/api/datasets');
      const data = await res.json();
      const list = data.datasets || [];
      datasetsCache = {};
      list.forEach((d) => {
        if (d.ref) datasetsCache[d.ref] = d;
      });
      return datasetsCache;
    } catch {
      return datasetsCache;
    }
  }

  async function fetchRelations() {
    const base = typeof window.getWorkspaceApiBase === 'function' ? window.getWorkspaceApiBase() : null;
    if (!base) return {};
    try {
      const res = await fetch(`${base}/relations`);
      const data = await res.json();
      relationsCache = data.relations || {};
      return relationsCache;
    } catch {
      return relationsCache;
    }
  }

  function schemaForStream(streamName) {
    const ds = datasetsCache[streamName];
    if (ds?.schema?.length) return ds.schema;
    const rel = relationsCache[streamName];
    if (rel?.schema?.length) return rel.schema;
    const cols = ds?.columns || rel?.columns || [];
    return cols.map((name) => ({ name, type: 'VARCHAR' }));
  }

  function pageSourceRef() {
    return currentPage()?.activeSource || '';
  }

  function propagatePageSource(ref) {
    const page = currentPage();
    if (!page) return;
    page.activeSource = ref || '';
    (page.widgets || []).forEach((w) => {
      if (widgetNoData(w.type)) return;
      if (!w.source) w.source = { kind: 'stream', ref: '' };
      w.source.ref = ref || '';
    });
    scheduleSave();
    renderPageSourcePicker();
    const widget = selectedWidgetId ? findWidget(selectedWidgetId) : null;
    renderFieldsPane(widget);
    currentWidgets().forEach((w) => refreshWidget(w.id));
  }

  async function renderPageSourcePicker() {
    const sel = document.getElementById('dashboard-page-source');
    if (!sel) return;
    await fetchDatasets();
    const page = currentPage();
    const current = page?.activeSource || '';
    const all = Object.values(datasetsCache);
    const streamEntries = all.filter((d) => d.is_stream);
    const fileEntries = all.filter((d) => !d.is_stream);
    const esc = (s) => String(s).replace(/"/g, '&quot;');
    let html = '<option value="">— select dataset —</option>';
    if (streamEntries.length) {
      html += '<optgroup label="Streams">';
      streamEntries.forEach((d) => {
        const fmt = d.format ? ` (${d.format})` : '';
        html += `<option value="${esc(d.ref)}" ${current === d.ref ? 'selected' : ''}>${esc(d.label)}${fmt}</option>`;
      });
      html += '</optgroup>';
    }
    if (fileEntries.length) {
      html += '<optgroup label="Files">';
      fileEntries.forEach((d) => {
        const fmt = d.format ? ` (${d.format})` : '';
        html += `<option value="${esc(d.ref)}" ${current === d.ref ? 'selected' : ''}>${esc(d.label)}${fmt}</option>`;
      });
      html += '</optgroup>';
    }
    sel.innerHTML = html;
    const selectedOpt = sel.options[sel.selectedIndex];
    sel.title = selectedOpt ? (selectedOpt.textContent || selectedOpt.value || '') : '';
    sel.removeEventListener('change', sel._sporeHandler);
    sel._sporeHandler = async () => {
      propagatePageSource(sel.value || '');
      const opt = sel.options[sel.selectedIndex];
      sel.title = opt ? (opt.textContent || opt.value || '') : '';
      await fetchRelations();
    };
    sel.addEventListener('change', sel._sporeHandler);
  }

  function activeFiltersFor(widget) {
    const controllers = pageControllerIds();
    const out = [];
    Object.entries(dashboardFilters).forEach(([cid, sel]) => {
      if (cid === widget.id) return;
      if (!controllers.has(cid)) return;
      if (!sel || !sel.field || sel.value === undefined || sel.value === null || sel.value === '') return;
      out.push({ field: sel.field, op: sel.op || 'eq', value: sel.value });
    });
    return out;
  }

  async function queryWidgetData(widget) {
    mapWellsToQuery(widget);
    const ref = widget.source?.ref || pageSourceRef();
    if (!ref) throw new Error('No data source selected — pick one in Data Fields');
    const extra = activeFiltersFor(widget);
    const transform = extra.length
      ? { ...widget.transform, filters: [...(widget.transform.filters || []), ...extra] }
      : widget.transform;
    const res = await fetch('/api/widgets/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        path: ref,
        stream: ref,
        transform,
        limit: transform?.limit || 500,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Query failed');
    return data;
  }

  function paletteFor(widget) {
    return PALETTES[widget.style?.palette] || PALETTES.default;
  }

  function pivotCartesian(rows, axisKey, legendKey, measureKeys) {
    const categories = [];
    const catSet = new Set();
    rows.forEach((row) => {
      const cat = String(row[axisKey] ?? '');
      if (!catSet.has(cat)) {
        catSet.add(cat);
        categories.push(cat);
      }
    });

    const measures = measureKeys.length ? measureKeys : ['value'];
    const series = [];

    if (legendKey) {
      const legends = [...new Set(rows.map((r) => String(r[legendKey] ?? '')))];
      measures.forEach((mKey) => {
        legends.forEach((leg) => {
          const data = categories.map((cat) => {
            const row = rows.find(
              (r) => String(r[axisKey] ?? '') === cat && String(r[legendKey] ?? '') === leg
            );
            return row ? Number(row[mKey]) || 0 : 0;
          });
          series.push({
            name: measures.length > 1 ? `${leg} · ${mKey}` : leg,
            data,
          });
        });
      });
    } else {
      measures.forEach((mKey) => {
        const data = categories.map((cat) => {
          const row = rows.find((r) => String(r[axisKey] ?? '') === cat);
          return row ? Number(row[mKey]) || 0 : 0;
        });
        series.push({ name: mKey, data });
      });
    }

    if (!series.length) {
      series.push({ name: 'Series', data: categories.map(() => 0) });
    }
    return { categories, series };
  }

  // Round a value up to a "nice" axis maximum (1, 2, 5 × 10^n) for gauges.
  function niceMax(value) {
    const v = Number(value);
    if (!Number.isFinite(v) || v <= 0) return 1;
    const mag = Math.pow(10, Math.floor(Math.log10(v)));
    const norm = v / mag;
    const step = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10;
    return step * mag;
  }

  function formatNum(value) {
    const v = Number(value);
    if (!Number.isFinite(v)) return String(value ?? '—');
    if (Math.abs(v) >= 1000) return Math.round(v).toLocaleString();
    return Number.isInteger(v) ? String(v) : v.toFixed(Math.abs(v) >= 100 ? 0 : 2);
  }

  function inferMapScope(axisField, rows) {
    const name = String(axisField || '').toLowerCase();
    if (/state|province|territory|^region$/i.test(name)) return 'usa';
    const sample = (rows || []).slice(0, 24).map((r) => String(r[axisField] ?? '').trim().toLowerCase()).filter(Boolean);
    if (!sample.length) return null;
    const usHits = sample.filter((v) => STATE_ALIASES[v] || Object.values(STATE_ALIASES).some((s) => s.toLowerCase() === v));
    if (usHits.length >= Math.max(1, Math.ceil(sample.length * 0.5))) return 'usa';
    return null;
  }

  function normalizeCountry(name) {
    const key = String(name ?? '').trim().toLowerCase();
    return COUNTRY_ALIASES[key] || String(name ?? '').trim();
  }

  function normalizeState(name) {
    const raw = String(name ?? '').trim();
    const key = raw.toLowerCase();
    if (STATE_ALIASES[key]) return STATE_ALIASES[key];
    const title = raw.replace(/\b\w/g, (c) => c.toUpperCase());
    return Object.values(STATE_ALIASES).find((s) => s.toLowerCase() === key) || title;
  }

  // Map raw location values to a scope's feature names. World aliases country
  // synonyms, USA expands state codes; bundled country maps already use clean
  // English names, so trim only and let ECharts match directly.
  function normalizeForScope(scope) {
    const region = mapScopeDef(scope).region;
    if (region === 'country') return normalizeCountry;
    if (region === 'state') return normalizeState;
    return (name) => String(name ?? '').trim();
  }

  function formatKpiValue(value, format) {
    const v = Number(value);
    if (!Number.isFinite(v)) return String(value ?? '—');
    if (format === 'currency') {
      return '$' + v.toLocaleString(undefined, { maximumFractionDigits: 0 });
    }
    if (format === 'percent') return `${(v * 100).toFixed(1)}%`;
    if (Math.abs(v) >= 100) return Math.round(v).toLocaleString();
    return formatNum(v);
  }

  function defaultKpiFormat(widget) {
    const agg = widget.wells?.fields?.[0] ? chipAgg(widget.wells.fields, 0) : 'sum';
    return agg === 'count' ? 'number' : 'currency';
  }

  function buildKpiSpec(widget, rows, columns, measureCols) {
    const kpiStyle = widget.style?.kpi || {};
    const yKey = measureCols[0] || columns[0];
    const row = rows[0] || {};
    const rawVal = yKey && row[yKey] !== undefined ? row[yKey] : Object.values(row)[0];
    const value = Number(rawVal);
    let target = kpiStyle.target;
    if (kpiStyle.targetColumn && row[kpiStyle.targetColumn] !== undefined) {
      target = Number(row[kpiStyle.targetColumn]);
    } else if (target !== '' && target != null) {
      target = Number(target);
    } else {
      target = null;
    }
    const pct = target && Number.isFinite(target) && target !== 0 && Number.isFinite(value)
      ? ((value - target) / target) * 100
      : null;
    const goodDir = kpiStyle.goodDirection || 'up';
    const deltaUp = pct != null && pct >= 0;
    const good = goodDir === 'up' ? deltaUp : !deltaUp;
    return {
      value: Number.isFinite(value) ? value : rawVal,
      target: Number.isFinite(target) ? target : null,
      pct,
      good,
      format: kpiStyle.format || defaultKpiFormat(widget),
      showDelta: kpiStyle.showDelta !== false,
    };
  }

  function buildTableSpec(widget, rows, columns, enc, measureCols) {
    const want = enc.columns?.length ? enc.columns : columns;
    const filtered = rows.map((r) => {
      const o = {};
      want.forEach((c) => { o[c] = r[c]; });
      return o;
    });
    const tableStyle = widget.style?.table || {};
    const dataBars = tableStyle.dataBars || [];
    const colMax = {};
    dataBars.forEach((col) => {
      let max = 0;
      filtered.forEach((r) => {
        const v = Number(r[col]);
        if (Number.isFinite(v) && v > max) max = v;
      });
      colMax[col] = max || 1;
    });
    return { columns: want, rows: filtered, tableStyle, measureCols, colMax };
  }

  function evalTableRule(rule, numVal) {
    if (numVal == null || !Number.isFinite(numVal)) return null;
    const op = rule.op || 'gt';
    const v = Number(rule.value);
    const v2 = Number(rule.value2);
    let match = false;
    if (op === 'gt') match = numVal > v;
    else if (op === 'lt') match = numVal < v;
    else if (op === 'gte') match = numVal >= v;
    else if (op === 'lte') match = numVal <= v;
    else if (op === 'between') match = numVal >= v && numVal <= v2;
    return match ? (rule.color || '#00A36C') : null;
  }

  function renderKpiElement(kpi) {
    const wrap = document.createElement('div');
    wrap.className = 'flex flex-col items-center justify-center h-full px-4 py-3 text-center';
    const valEl = document.createElement('div');
    valEl.className = 'text-3xl font-black text-slate-900 leading-none';
    valEl.textContent = formatKpiValue(kpi.value, kpi.format);
    wrap.appendChild(valEl);
    if (kpi.target != null) {
      const targetEl = document.createElement('div');
      targetEl.className = 'text-[10px] text-slate-400 font-bold uppercase tracking-widest mt-2';
      targetEl.textContent = `Target ${formatKpiValue(kpi.target, kpi.format)}`;
      wrap.appendChild(targetEl);
    }
    if (kpi.showDelta && kpi.pct != null) {
      const pill = document.createElement('div');
      pill.className = `inline-flex items-center gap-1 mt-2 px-2 py-0.5 rounded-pill text-[10px] font-black ${kpi.good ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-600'}`;
      pill.innerHTML = `<span class="material-symbols-outlined text-[12px]">${kpi.pct >= 0 ? 'arrow_upward' : 'arrow_downward'}</span>${Math.abs(kpi.pct).toFixed(1)}% vs target`;
      wrap.appendChild(pill);
    }
    return wrap;
  }

  function renderTableElement(spec) {
    const { columns, rows, tableStyle, colMax } = spec;
    const groupBy = tableStyle.groupBy || '';
    const rules = tableStyle.rules || [];
    const dataBars = tableStyle.dataBars || [];
    const wrap = document.createElement('div');
    wrap.className = 'overflow-auto h-full text-[10px] font-mono';
    const table = document.createElement('table');
    table.className = 'w-full border-collapse';
    const thead = document.createElement('thead');
    const hr = document.createElement('tr');
    columns.forEach((c) => {
      const th = document.createElement('th');
      th.className = 'sticky top-0 bg-slate-50 border-b border-slate-200 px-2 py-1 text-left';
      th.textContent = c;
      hr.appendChild(th);
    });
    thead.appendChild(hr);
    table.appendChild(thead);
    const tbody = document.createElement('tbody');
    let lastGroup = null;
    rows.slice(0, 200).forEach((row) => {
      if (groupBy) {
        const g = String(row[groupBy] ?? '');
        if (g !== lastGroup) {
          lastGroup = g;
          const gtr = document.createElement('tr');
          const gtd = document.createElement('td');
          gtd.colSpan = columns.length;
          gtd.className = 'bg-slate-100 border-b border-slate-200 px-2 py-1 font-black text-[9px] uppercase tracking-widest text-slate-600';
          gtd.textContent = g;
          gtr.appendChild(gtd);
          tbody.appendChild(gtr);
        }
      }
      const tr = document.createElement('tr');
      columns.forEach((c) => {
        const td = document.createElement('td');
        td.className = 'border-b border-slate-100 px-2 py-0.5 relative';
        const raw = row[c];
        const numVal = Number(raw);
        const isNum = Number.isFinite(numVal);
        rules.forEach((rule) => {
          if (rule.col !== c) return;
          const color = evalTableRule(rule, isNum ? numVal : null);
          if (!color) return;
          if (rule.kind === 'text') td.style.color = color;
          else if (rule.kind === 'cell') td.style.backgroundColor = color + '22';
        });
        if (dataBars.includes(c) && isNum) {
          const pct = Math.min(100, Math.max(0, (numVal / (colMax[c] || 1)) * 100));
          td.style.backgroundImage = `linear-gradient(90deg, rgba(0,163,108,0.18) ${pct}%, transparent ${pct}%)`;
        }
        const dotRule = rules.find((r) => r.col === c && r.kind === 'dot');
        if (dotRule) {
          const color = evalTableRule(dotRule, isNum ? numVal : null);
          if (color) {
            const dot = document.createElement('span');
            dot.className = 'inline-block w-2 h-2 rounded-full mr-1 align-middle';
            dot.style.backgroundColor = color;
            td.appendChild(dot);
          }
        }
        const text = document.createElement('span');
        text.textContent = isNum ? formatNum(numVal) : String(raw ?? '');
        td.appendChild(text);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    return wrap;
  }

  function listParamNames() {
    return (dashboardState.pages || [])
      .flatMap((p) => p.widgets || [])
      .filter((w) => w.type === 'parameter' && w.param?.name)
      .map((w) => w.param.name);
  }

  function getParamMultiplier(name) {
    if (!name) return 1;
    const paramWidget = (dashboardState.pages || [])
      .flatMap((p) => p.widgets || [])
      .find((w) => w.type === 'parameter' && w.param?.name === name);
    if (!paramWidget) return 1;
    const base = Number(paramWidget.param?.value);
    const baseline = Number.isFinite(base) ? base : 0;
    const current = dashboardParams[name] != null ? Number(dashboardParams[name]) : baseline;
    return 1 + (Number.isFinite(current) ? current : baseline) / 100;
  }

  function applyParamScale(widget, rows, columns) {
    const paramName = widget.style?.scaleByParam;
    if (!paramName) return rows;
    const mult = getParamMultiplier(paramName);
    if (mult === 1) return rows;
    const { measureCols } = resolveQueryColumns(widget, columns);
    const cols = measureCols.length ? measureCols : columns.filter((c) =>
      rows.some((r) => Number.isFinite(Number(r[c])))
    );
    return rows.map((row) => {
      const copy = { ...row };
      cols.forEach((col) => {
        const v = Number(copy[col]);
        if (Number.isFinite(v)) copy[col] = v * mult;
      });
      return copy;
    });
  }

  function refreshParamSubscribers(name) {
    (dashboardState.pages || []).forEach((page) => {
      (page.widgets || []).forEach((w) => {
        if (w.style?.scaleByParam === name) refreshWidget(w.id);
      });
    });
  }

  const _mapPromises = {};

  // Lazily fetch + register a scope's GeoJSON, cached per scope after success.
  function ensureMapForScope(scope) {
    if (typeof echarts === 'undefined') {
      return Promise.reject(new Error('ECharts is not loaded'));
    }
    const def = mapScopeDef(scope);
    if (typeof echarts.getMap === 'function' && echarts.getMap(def.mapName)) {
      return Promise.resolve();
    }
    if (_mapPromises[def.mapName]) return _mapPromises[def.mapName];
    _mapPromises[def.mapName] = registerScopeMap(def).catch((e) => {
      _mapPromises[def.mapName] = null; // allow a later retry
      throw e;
    });
    return _mapPromises[def.mapName];
  }

  function buildMapOption(spec) {
    const palette = spec.palette || PALETTES.default;
    const def = mapScopeDef(spec.scope);
    return {
      tooltip: {
        trigger: 'item',
        formatter: (p) =>
          `${p.name}: ${p.value !== undefined && p.value !== null && !Number.isNaN(p.value) ? formatNum(p.value) : 'N/A'}`,
      },
      visualMap: {
        min: 0,
        max: spec.maxVal,
        calculable: true,
        orient: 'horizontal',
        left: 'center',
        bottom: 4,
        itemWidth: 12,
        itemHeight: 60,
        textStyle: { fontSize: 9 },
        inRange: { color: ['#e2e8f0', palette[0]] },
      },
      series: [{
        type: 'map',
        map: def.mapName,
        roam: true,
        scaleLimit: { min: 1, max: 12 },
        emphasis: { label: { show: false }, itemStyle: { areaColor: palette[1] || palette[0] } },
        itemStyle: { borderColor: '#cbd5e1', borderWidth: 0.5, areaColor: '#f1f5f9' },
        data: spec.data,
      }],
    };
  }

  // Overlay +/−/reset zoom controls on a map chart. Map series support roam
  // (wheel + drag); the buttons drive the same `zoom`/`center` programmatically
  // so it's discoverable without a mouse wheel.
  function attachMapZoomControls(container, inst) {
    const wrap = document.createElement('div');
    wrap.className = 'absolute top-1.5 right-1.5 z-10 flex flex-col gap-1';
    wrap.innerHTML = `
      <button type="button" data-mapzoom="in" title="Zoom in" class="h-6 w-6 flex items-center justify-center rounded-md bg-white/95 border border-slate-200 shadow-sm text-slate-600 hover:bg-slate-50 hover:text-primary"><span class="material-symbols-outlined text-[15px] leading-none">add</span></button>
      <button type="button" data-mapzoom="out" title="Zoom out" class="h-6 w-6 flex items-center justify-center rounded-md bg-white/95 border border-slate-200 shadow-sm text-slate-600 hover:bg-slate-50 hover:text-primary"><span class="material-symbols-outlined text-[15px] leading-none">remove</span></button>
      <button type="button" data-mapzoom="reset" title="Reset view" class="h-6 w-6 flex items-center justify-center rounded-md bg-white/95 border border-slate-200 shadow-sm text-slate-600 hover:bg-slate-50 hover:text-primary"><span class="material-symbols-outlined text-[14px] leading-none">center_focus_weak</span></button>`;

    const seriesZoom = () => {
      const s = (inst.getOption().series || [])[0] || {};
      return { zoom: s.zoom || 1, center: s.center };
    };
    const applyZoom = (factor) => {
      const { zoom, center } = seriesZoom();
      const next = Math.max(1, Math.min(12, zoom * factor));
      inst.setOption({ series: [{ zoom: next, center }] });
    };

    wrap.querySelector('[data-mapzoom="in"]').addEventListener('click', (e) => { e.stopPropagation(); applyZoom(1.6); });
    wrap.querySelector('[data-mapzoom="out"]').addEventListener('click', (e) => { e.stopPropagation(); applyZoom(1 / 1.6); });
    wrap.querySelector('[data-mapzoom="reset"]').addEventListener('click', (e) => {
      e.stopPropagation();
      if (inst._mapSpec) inst.setOption(buildMapOption(inst._mapSpec), true);
    });

    container.style.position = container.style.position || 'relative';
    container.appendChild(wrap);
  }

  function buildEchartsOption(widget, rows, columns) {
    const type = (widget.type || 'bar').toLowerCase();
    const enc = widget.encoding || {};
    const palette = paletteFor(widget);
    const showLegend = widget.style?.showLegend !== false;
    const hint = chartConfigHint(widget);
    if (hint) return { _placeholder: hint };
    const { dimCols, measureCols } = resolveQueryColumns(widget, columns);

    if (type === 'kpi') {
      return { _kpi: buildKpiSpec(widget, rows, columns, measureCols) };
    }

    if (type === 'table') {
      return { _table: buildTableSpec(widget, rows, columns, enc, measureCols) };
    }

    if (type === 'scatter') {
      const xKey = enc.x || columns[0];
      const yKey = enc.y || columns[1];
      const sizeKey = enc.size;
      const seriesKey = enc.series;
      if (!xKey || !yKey) return { _placeholder: 'Add X Values and Y Values in the wells.' };
      const pointValue = (r) => [
        Number(r[xKey]) || 0,
        Number(r[yKey]) || 0,
        sizeKey ? Number(r[sizeKey]) || 10 : 10,
      ];
      const scatterSeries = (name, data) => ({
        name,
        type: 'scatter',
        symbolSize: (d) => (Array.isArray(d) ? d[2] : 10),
        data,
      });
      if (seriesKey) {
        const groups = {};
        rows.forEach((r) => {
          const k = String(r[seriesKey] ?? '');
          if (!groups[k]) groups[k] = [];
          groups[k].push(pointValue(r));
        });
        const seriesList = Object.entries(groups).map(([name, data]) => scatterSeries(name, data));
        return {
          color: palette,
          tooltip: { trigger: 'item' },
          legend: showLegend ? { top: 0, type: 'scroll' } : undefined,
          grid: { left: 48, right: 16, top: seriesList.length > 1 ? 40 : 32, bottom: 32 },
          xAxis: { type: 'value', scale: true },
          yAxis: { type: 'value', scale: true },
          series: seriesList,
        };
      }
      return {
        color: palette,
        tooltip: { trigger: 'item' },
        grid: { left: 48, right: 16, top: 32, bottom: 32 },
        xAxis: { type: 'value', scale: true },
        yAxis: { type: 'value', scale: true },
        series: [scatterSeries('Series', rows.map(pointValue))],
      };
    }

    if (type === 'heatmap') {
      const xKey = dimCols[1] || enc.x;
      const yKey = dimCols[0] || enc.y;
      const zKey = measureCols[0] || enc.z;
      if (!xKey || !yKey || !zKey) return { _placeholder: hint || 'Configure Rows, Columns, and Values.' };
      const xCats = [...new Set(rows.map((r) => String(r[xKey] ?? '')))];
      const yCats = [...new Set(rows.map((r) => String(r[yKey] ?? '')))];
      const data = rows.map((r) => [
        xCats.indexOf(String(r[xKey] ?? '')),
        yCats.indexOf(String(r[yKey] ?? '')),
        Number(r[zKey]) || 0,
      ]);
      const zMax = data.length ? Math.max(...data.map((d) => d[2]), 1) : 1;
      return {
        tooltip: { position: 'top' },
        grid: { left: 56, right: 24, top: 24, bottom: 48 },
        xAxis: { type: 'category', data: xCats, splitArea: { show: true } },
        yAxis: { type: 'category', data: yCats, splitArea: { show: true } },
        visualMap: { min: 0, max: zMax, calculable: true, orient: 'horizontal', left: 'center', bottom: 0 },
        series: [{ type: 'heatmap', data, label: { show: false } }],
      };
    }

    if (type === 'pie') {
      const xKey = dimCols[0] || enc.x;
      const yKey = measureCols[0] || enc.y;
      if (!xKey || !yKey) return { _placeholder: hint || 'Configure Legend and Values.' };
      return {
        color: palette,
        tooltip: { trigger: 'item' },
        legend: showLegend ? { bottom: 0, type: 'scroll' } : undefined,
        series: [{
          type: 'pie',
          radius: ['35%', '65%'],
          data: rows.map((r) => ({ name: String(r[xKey] ?? ''), value: Number(r[yKey]) || 0 })),
        }],
      };
    }

    if (type === 'map') {
      const xKey = dimCols[0] || enc.x;
      const yKey = measureCols[0] || enc.y;
      if (!xKey || !yKey) return { _placeholder: hint || 'Configure Location and Values.' };
      const inferred = inferMapScope(xKey, rows);
      if (inferred && (!widget.style.mapScope || widget.style.mapScope === 'world')) {
        widget.style.mapScope = inferred;
      }
      const scope = widget.style?.mapScope || 'world';
      const normalize = normalizeForScope(scope);
      const data = rows.map((r) => ({
        name: normalize(r[xKey]),
        value: Number(r[yKey]) || 0,
      }));
      const maxVal = data.length ? Math.max(...data.map((d) => d.value), 1) : 1;
      return { _worldmap: { data, maxVal, palette, scope } };
    }

    if (type === 'funnel') {
      const xKey = dimCols[0] || enc.x;
      const yKey = measureCols[0] || enc.y;
      if (!xKey || !yKey) return { _placeholder: hint || 'Configure Stage and Values.' };
      const data = rows.map((r) => ({ name: String(r[xKey] ?? ''), value: Number(r[yKey]) || 0 }));
      return {
        color: palette,
        tooltip: { trigger: 'item', formatter: '{b}: {c}' },
        legend: showLegend ? { bottom: 0, type: 'scroll' } : undefined,
        series: [{
          type: 'funnel',
          left: '8%',
          right: '8%',
          top: 16,
          bottom: showLegend ? 32 : 16,
          minSize: '0%',
          sort: 'descending',
          gap: 2,
          label: { show: true, position: 'inside', fontSize: 10 },
          data,
        }],
      };
    }

    if (type === 'gauge') {
      const yKey = measureCols[0] || enc.y || columns[0];
      const row = rows[0] || {};
      const raw = yKey && row[yKey] !== undefined ? Number(row[yKey]) : Number(Object.values(row)[0]);
      const val = Number.isFinite(raw) ? raw : 0;
      return {
        color: palette,
        series: [{
          type: 'gauge',
          min: 0,
          max: niceMax(val),
          progress: { show: true, width: 14, itemStyle: { color: palette[0] } },
          axisLine: { lineStyle: { width: 14 } },
          axisLabel: { fontSize: 9, distance: 14 },
          pointer: { itemStyle: { color: palette[0] } },
          detail: {
            valueAnimation: true,
            fontSize: 22,
            offsetCenter: [0, '74%'],
            formatter: (v) => formatNum(v),
          },
          title: { show: !!yKey, offsetCenter: [0, '96%'], fontSize: 10 },
          data: [{ value: val, name: yKey || '' }],
        }],
      };
    }

    if (type === 'treemap') {
      const catKey = dimCols[0] || enc.x;
      const groupKey = dimCols.length > 1 ? dimCols[1] : '';
      const valKey = measureCols[0] || enc.y;
      if (!catKey || !valKey) return { _placeholder: hint || 'Configure Category and Values.' };
      let data;
      const hasGroup = groupKey && groupKey !== catKey;
      if (hasGroup) {
        const groups = {};
        rows.forEach((r) => {
          const g = String(r[groupKey] ?? '');
          (groups[g] = groups[g] || []).push({
            name: String(r[catKey] ?? ''),
            value: Number(r[valKey]) || 0,
          });
        });
        data = Object.entries(groups).map(([name, children]) => ({ name, children }));
      } else {
        data = rows.map((r) => ({ name: String(r[catKey] ?? ''), value: Number(r[valKey]) || 0 }));
      }
      return {
        color: palette,
        tooltip: { trigger: 'item', formatter: '{b}: {c}' },
        series: [{
          type: 'treemap',
          roam: false,
          breadcrumb: { show: hasGroup, height: 18, bottom: 0 },
          label: { show: true, fontSize: 10 },
          upperLabel: hasGroup ? { show: true, height: 16, fontSize: 9 } : undefined,
          levels: hasGroup
            ? [{ itemStyle: { borderColor: '#fff', borderWidth: 2, gapWidth: 2 } }, { itemStyle: { gapWidth: 1 } }]
            : undefined,
          data,
        }],
      };
    }

    if (type === 'radar') {
      const axisK = dimCols[0] || enc.x;
      let legendK = dimCols.length > 1 ? dimCols[1] : (enc.series || '');
      if (legendK === axisK) legendK = '';
      const mKeys = measureCols.length ? measureCols : [enc.y].filter(Boolean);
      if (!axisK || !mKeys.length) return { _placeholder: hint || 'Add Indicators and Values in the wells.' };
      const { categories, series } = pivotCartesian(rows, axisK, legendK, mKeys);
      let maxVal = 0;
      series.forEach((s) => s.data.forEach((v) => { if (v > maxVal) maxVal = v; }));
      maxVal = maxVal > 0 ? maxVal : 1;
      return {
        color: palette,
        tooltip: { trigger: 'item' },
        legend: showLegend && series.length > 1 ? { top: 0, type: 'scroll' } : undefined,
        radar: {
          indicator: categories.map((c) => ({ name: c, max: maxVal })),
          radius: '62%',
          center: ['50%', series.length > 1 ? '56%' : '50%'],
          axisName: { fontSize: 9 },
        },
        series: [{
          type: 'radar',
          data: series.map((s) => ({ name: s.name, value: s.data, areaStyle: { opacity: 0.1 } })),
        }],
      };
    }

    const axisKey = dimCols[0] || enc.x;
    let legendKey = dimCols.length > 1 ? dimCols[1] : (enc.series || '');
    if (legendKey === axisKey) legendKey = '';
    const measureKeys = measureCols.length ? measureCols : [enc.y].filter(Boolean);
    if (!axisKey || !measureKeys.length) {
      return { _placeholder: hint || 'Add Axis and Values in the wells.' };
    }

    const { categories, series } = pivotCartesian(rows, axisKey, legendKey, measureKeys);
    const seriesType = type === 'line' ? 'line' : type === 'area' ? 'line' : 'bar';

    return {
      color: palette,
      tooltip: { trigger: 'axis' },
      legend: showLegend && series.length > 1 ? { top: 0, type: 'scroll' } : undefined,
      grid: { left: 48, right: 16, top: series.length > 1 ? 40 : 28, bottom: 32 },
      xAxis: { type: 'category', data: categories, axisLabel: { fontSize: 10, rotate: categories.length > 8 ? 25 : 0 } },
      yAxis: { type: 'value', axisLabel: { fontSize: 10 } },
      series: series.map((s) => ({
        name: s.name,
        type: seriesType,
        data: s.data,
        stack: type === 'area' ? 'total' : undefined,
        areaStyle: type === 'area' ? {} : undefined,
        smooth: type === 'line' || type === 'area',
      })),
    };
  }

  function renderTextWidget(widget, container) {
    container.innerHTML = '';
    const wrap = document.createElement('div');
    wrap.className = 'prose prose-slate max-w-none text-sm h-full overflow-auto p-3 scrollbar-thin';
    const raw = widget.text || '';
    if (typeof marked !== 'undefined') {
      wrap.innerHTML = marked.parse(raw);
    } else {
      wrap.textContent = raw;
    }
    container.appendChild(wrap);
  }

  // Navigation button: jumps to another dashboard page in View mode. In Edit
  // mode it selects the widget so its target page can be configured.
  function renderButtonWidget(widget, container) {
    container.innerHTML = '';
    const target = widget.nav?.target || '';
    const targetExists = (dashboardState.pages || []).some((p) => p.id === target);
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className =
      'w-full h-full flex items-center justify-center gap-1.5 rounded-lg bg-primary text-white text-[11px] font-black uppercase tracking-widest shadow-tactile hover:translate-y-[-1px] transition-all px-3';
    const icon = document.createElement('span');
    icon.className = 'material-symbols-outlined text-[15px] shrink-0';
    icon.textContent = 'arrow_forward';
    const label = document.createElement('span');
    label.className = 'truncate';
    label.textContent = widget.title || 'Go to page';
    btn.append(icon, label);
    if (!targetExists && !editMode) {
      btn.classList.add('opacity-60');
      btn.title = 'No target page configured';
    }
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (editMode) {
        selectWidget(widget.id);
        return;
      }
      if (targetExists) switchPage(target);
    });
    container.appendChild(btn);
  }

  function renderParameterWidget(widget, container) {
    container.innerHTML = '';
    ensureWidget(widget);
    const p = widget.param || {};
    const name = p.name || 'param';
    const min = Number(p.min) || 0;
    const max = Number(p.max) || 100;
    const step = Number(p.step) || 1;
    const val = dashboardParams[name] != null ? Number(dashboardParams[name]) : Number(p.value) || 0;
    dashboardParams[name] = val;
    const wrap = document.createElement('div');
    wrap.className = 'flex flex-col justify-center h-full px-4 py-2 gap-2';
    const label = document.createElement('div');
    label.className = 'text-[9px] font-black uppercase tracking-widest text-slate-500';
    label.textContent = widget.title || name;
    const row = document.createElement('div');
    row.className = 'flex items-center gap-2';
    const slider = document.createElement('input');
    slider.type = 'range';
    slider.min = String(min);
    slider.max = String(max);
    slider.step = String(step);
    slider.value = String(val);
    slider.className = 'flex-1 accent-primary';
    const valEl = document.createElement('span');
    valEl.className = 'text-[11px] font-black text-primary min-w-[3rem] text-right';
    valEl.textContent = `${val}%`;
    slider.addEventListener('input', () => {
      const v = Number(slider.value);
      dashboardParams[name] = v;
      valEl.textContent = `${v}%`;
      refreshParamSubscribers(name);
    });
    row.append(slider, valEl);
    wrap.append(label, row);
    container.appendChild(wrap);
  }

  function renderWidgetBody(widget, container, queryResult) {
    const rows = applyParamScale(widget, queryResult?.rows || [], queryResult?.columns || []);
    const columns = queryResult?.columns || [];
    container.innerHTML = '';

    if (chartInstances[widget.id]) {
      chartInstances[widget.id].dispose();
      delete chartInstances[widget.id];
    }

    if (widget.type === 'parameter') {
      renderParameterWidget(widget, container);
      return;
    }

    if (widget.type === 'slicer') {
      renderSlicerBody(widget, container, rows, columns);
      return;
    }

    const opt = applyControllerEmphasis(widget, buildEchartsOption(widget, rows, columns));

    if (opt._placeholder) {
      const el = document.createElement('p');
      el.className = 'text-[10px] text-slate-400 font-medium p-4 text-center';
      el.textContent = opt._placeholder;
      container.appendChild(el);
      return;
    }

    if (opt._kpi) {
      container.appendChild(renderKpiElement(opt._kpi));
      return;
    }

    if (opt._table) {
      container.appendChild(renderTableElement(opt._table));
      return;
    }

    const chartEl = document.createElement('div');
    chartEl.className = 'w-full h-full min-h-[120px]';
    container.appendChild(chartEl);
    if (typeof echarts === 'undefined') return;

    const inst = echarts.init(chartEl);
    chartInstances[widget.id] = inst;
    new ResizeObserver(() => inst.resize()).observe(container);

    if (opt._worldmap) {
      const scope = opt._worldmap.scope || 'world';
      inst._mapSpec = opt._worldmap;
      inst.showLoading({ text: 'Loading map…', fontSize: 11, color: '#00A36C' });
      ensureMapForScope(scope)
        .then(() => {
          if (chartInstances[widget.id] !== inst) return;
          inst.hideLoading();
          inst.setOption(buildMapOption(opt._worldmap));
          attachMapZoomControls(container, inst);
          attachCrossFilter(widget, inst);
        })
        .catch((e) => {
          inst.hideLoading();
          container.innerHTML = `<p class="text-[10px] text-amber-600 p-4 text-center font-medium">Map data could not be loaded (${e.message}). Check your network connection.</p>`;
          if (chartInstances[widget.id] === inst) {
            inst.dispose();
            delete chartInstances[widget.id];
          }
        });
      return;
    }

    inst.setOption(opt);
    attachCrossFilter(widget, inst);
  }

  // Cross-filtering (C): clicking a category in a chart publishes a selection
  // onto the shared bus so widgets that opted in re-query against it.
  function attachCrossFilter(widget, inst) {
    if (!CLICK_FILTER_TYPES.includes(widget.type)) return;
    const field = widget.encoding?.x;
    if (!field) return;
    inst.on('click', (params) => {
      const value = widget.type === 'pie' ? params.name : params.name;
      if (value === undefined || value === null || value === '') return;
      const current = dashboardFilters[widget.id];
      if (current && String(current.value) === String(value)) {
        clearSelection(widget.id);
      } else {
        publishSelection(widget.id, { field, op: 'eq', value });
      }
    });
  }

  function pageControllerIds() {
    return new Set(
      currentWidgets()
        .filter((w) => w.type === 'slicer' || CLICK_FILTER_TYPES.includes(w.type))
        .map((w) => w.id)
    );
  }

  function activeControllerSelections() {
    const controllers = pageControllerIds();
    return Object.entries(dashboardFilters)
      .filter(([cid, sel]) => controllers.has(cid) && sel?.field && sel.value !== undefined && sel.value !== null && sel.value !== '')
      .map(([cid, sel]) => ({ cid, sel }));
  }

  // Re-render every data widget on the page so cross-highlighting (dimmed,
  // non-selected marks on the source chart) and the per-widget filter badges
  // stay in sync. The clicked controller is included so its selected slice
  // gets emphasized; other widgets re-query against the active selection.
  function refreshAllPageWidgets() {
    currentWidgets().forEach((w) => {
      if (!widgetNoData(w.type)) refreshWidget(w.id);
    });
    updateCrossFilterCues();
  }

  function clearAllCrossFilters() {
    dashboardFilters = {};
    refreshAllPageWidgets();
  }

  // Visual context lives inside the widgets themselves (Power BI style): the
  // source chart dims non-selected marks and shows a "Slicing" badge; every
  // affected widget shows a "Filtered by" badge in its header. No global bar.
  function updateCrossFilterCues() {
    const active = activeControllerSelections();
    const activeIds = new Set(active.map((a) => a.cid));
    const esc = (s) => String(s ?? '').replace(/"/g, '&quot;');

    currentWidgets().forEach((widget) => {
      const badge = document.querySelector(`[data-filter-badge="${widget.id}"]`);
      const content = document.querySelector(`[gs-id="${widget.id}"] .grid-stack-item-content`);
      if (!badge) return;

      if (widgetNoData(widget.type)) {
        badge.innerHTML = '';
        badge.classList.add('hidden');
        if (content) { content.style.outline = ''; content.style.outlineOffset = ''; }
        return;
      }

      const isSource = activeIds.has(widget.id);
      const incoming = activeFiltersFor(widget);

      if (isSource) {
        const sel = dashboardFilters[widget.id];
        badge.classList.remove('hidden');
        badge.innerHTML = `<span class="inline-flex items-center gap-1 h-5 px-1.5 rounded-pill bg-primary text-white text-[8px] font-black uppercase tracking-widest" title="This chart is filtering the page">
            <span class="material-symbols-outlined text-[11px] leading-none">ads_click</span>${esc(sel.value)}
            <button type="button" data-clear-filter="${esc(widget.id)}" class="ml-0.5 text-white/80 hover:text-white leading-none" title="Clear">&times;</button>
          </span>`;
      } else if (incoming.length) {
        const parts = incoming.map((f) => `${esc(f.field)} = ${esc(f.value)}`).join(' · ');
        badge.classList.remove('hidden');
        badge.innerHTML = `<span class="inline-flex items-center gap-1 h-5 px-1.5 rounded-pill bg-primary-soft border border-primary/25 text-primary-dark text-[8px] font-black uppercase tracking-widest" title="Filtered by another chart">
            <span class="material-symbols-outlined text-[11px] leading-none">filter_alt</span>${parts}
          </span>`;
      } else {
        badge.innerHTML = '';
        badge.classList.add('hidden');
      }

      // Use outline (not Tailwind ring/box-shadow) so the cross-filter accent
      // never clobbers the selection ring applied by selectWidget().
      if (content) {
        if (isSource) {
          content.style.outline = '2px solid #00A36C';
          content.style.outlineOffset = '-2px';
        } else if (incoming.length) {
          content.style.outline = '1px solid rgba(0,163,108,0.4)';
          content.style.outlineOffset = '-1px';
        } else {
          content.style.outline = '';
          content.style.outlineOffset = '';
        }
      }

      badge.querySelectorAll('[data-clear-filter]').forEach((btn) => {
        btn.onclick = (e) => {
          e.stopPropagation();
          clearSelection(btn.dataset.clearFilter);
        };
      });
    });
  }

  // Dim non-selected marks on the controlling chart so the active slice is
  // obvious. Operates in place on the ECharts option's series.
  function applyControllerEmphasis(widget, option) {
    const sel = dashboardFilters[widget.id];
    if (!option || !Array.isArray(option.series)) return option;
    if (!sel || !sel.field || sel.value === undefined || sel.value === null || sel.value === '') return option;
    if (sel.field !== widget.encoding?.x) return option;
    const target = String(sel.value);
    const cats = Array.isArray(option.xAxis?.data) ? option.xAxis.data.map((c) => String(c)) : null;

    option.series.forEach((s) => {
      if (!s || !Array.isArray(s.data)) return;
      if (s.type === 'pie' || s.type === 'funnel') {
        s.data = s.data.map((d) => {
          const item = (d && typeof d === 'object') ? { ...d } : { value: d };
          const on = String(item.name) === target;
          item.itemStyle = {
            ...(item.itemStyle || {}),
            opacity: on ? 1 : 0.25,
            borderColor: on ? '#0f172a' : 'transparent',
            borderWidth: on ? 2 : 0,
          };
          return item;
        });
      } else if (s.type === 'bar' && cats) {
        s.data = s.data.map((v, i) => {
          const val = (v && typeof v === 'object') ? v.value : v;
          const on = cats[i] === target;
          return {
            value: val,
            itemStyle: { opacity: on ? 1 : 0.25, borderColor: on ? '#0f172a' : 'transparent', borderWidth: on ? 1.5 : 0 },
          };
        });
      }
    });
    return option;
  }

  function publishSelection(controllerId, selection) {
    dashboardFilters[controllerId] = selection;
    refreshAllPageWidgets();
  }

  function clearSelection(controllerId) {
    delete dashboardFilters[controllerId];
    refreshAllPageWidgets();
  }

  function renderSlicerBody(widget, container, rows, columns) {
    container.innerHTML = '';
    const field = widget.encoding?.x || columns[0];
    if (!field) {
      const el = document.createElement('p');
      el.className = 'text-[10px] text-slate-400 font-medium p-4 text-center';
      el.textContent = 'Add a field to slice the dashboard by.';
      container.appendChild(el);
      return;
    }
    const values = [];
    const seen = new Set();
    rows.forEach((r) => {
      const v = r[field];
      const key = String(v);
      if (!seen.has(key)) {
        seen.add(key);
        values.push(v);
      }
    });

    const wrap = document.createElement('div');
    wrap.className = 'flex flex-wrap gap-1 p-2 overflow-auto h-full content-start scrollbar-thin';
    const active = dashboardFilters[widget.id];

    const mkBtn = (label, value, isActive) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = isActive
        ? 'h-6 px-2 rounded-pill bg-primary text-white text-[10px] font-bold'
        : 'h-6 px-2 rounded-pill bg-white border border-slate-200 text-slate-600 text-[10px] font-bold hover:border-primary/50';
      btn.textContent = label;
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (value === null) {
          clearSelection(widget.id);
        } else if (active && String(active.value) === String(value)) {
          clearSelection(widget.id);
        } else {
          publishSelection(widget.id, { field, op: 'eq', value });
        }
        renderSlicerBody(widget, container, rows, columns);
      });
      return btn;
    };

    wrap.appendChild(mkBtn('All', null, !active));
    values.slice(0, 200).forEach((v) => {
      wrap.appendChild(mkBtn(String(v), v, active && String(active.value) === String(v)));
    });
    container.appendChild(wrap);
  }

  async function refreshWidget(widgetId) {
    const widget = findWidget(widgetId);
    if (!widget) return;
    const body = document.querySelector(`[data-widget-body="${widgetId}"]`);
    if (!body) return;
    if (widgetNoData(widget.type)) {
      if (widget.type === 'button') renderButtonWidget(widget, body);
      else if (widget.type === 'parameter') renderParameterWidget(widget, body);
      else renderTextWidget(widget, body);
      return;
    }
    body.innerHTML = '<p class="text-[10px] text-slate-400 p-4">Loading…</p>';
    try {
      mapWellsToQuery(widget);
      const result = await queryWidgetData(widget);
      renderWidgetBody(widget, body, result);
    } catch (e) {
      body.innerHTML = `<p class="text-[10px] text-red-500 p-4 font-mono">${e.message}</p>`;
    }
  }

  function setDeckCollapsed(deckId, collapsed) {
    const deck = document.getElementById(deckId);
    if (!deck) return;
    deck.classList.toggle('deck-collapsed', collapsed);
    deck.classList.toggle('w-12', collapsed);
    deck.classList.toggle('w-56', !collapsed);

    const header = deck.querySelector('.deck-header');
    if (header) {
      header.classList.toggle('justify-center', collapsed);
      header.classList.toggle('justify-between', !collapsed);
    }
    deck.querySelector('.deck-body')?.classList.toggle('hidden', collapsed);
    deck.querySelector('.deck-title')?.classList.toggle('hidden', collapsed);
    deck.querySelector('.toggle-icon')?.classList.toggle('hidden', collapsed);

    // Charts depend on container width; resize after the width transition.
    setTimeout(() => {
      Object.values(chartInstances).forEach((c) => {
        try { c.resize(); } catch (_) { /* noop */ }
      });
    }, 320);
  }

  function toggleDashboardDeck(deckId) {
    const deck = document.getElementById(deckId);
    if (!deck) return;
    setDeckCollapsed(deckId, !deck.classList.contains('deck-collapsed'));
  }

  function selectWidget(widgetId) {
    selectedWidgetId = widgetId;
    document.querySelectorAll('.grid-stack-item-content').forEach((el) => {
      el.classList.remove('ring-2', 'ring-primary', 'ring-offset-1');
    });
    const item = document.querySelector(`[gs-id="${widgetId}"] .grid-stack-item-content`);
    if (item) item.classList.add('ring-2', 'ring-primary', 'ring-offset-1');
    // Reveal the authoring controls when a widget gets focus.
    setDeckCollapsed('deck-viz', false);
    renderAuthoringPane();
  }

  function defaultWellForField(widget, fieldName, dtype) {
    const type = widget.type || 'bar';
    const reg = getRegistry(type);
    const numeric = isNumericType(dtype);
    const chip = { field: fieldName, agg: defaultAggForField(fieldName, schemaForStream(widget.source?.ref)) };

    if (type === 'scatter') {
      if (numeric && !(widget.wells.xValues || []).length) return { wellId: 'xValues', chip };
      if (numeric && !(widget.wells.yValues || []).length) return { wellId: 'yValues', chip: { ...chip, agg: 'avg' } };
      if (!numeric && !(widget.wells.legend || []).length) return { wellId: 'legend', chip: { field: fieldName } };
      return null;
    }
    if (type === 'kpi') return { wellId: 'fields', chip };
    if (type === 'gauge') return { wellId: 'value', chip };
    if (type === 'funnel') {
      if (numeric && !(widget.wells.values || []).length) return { wellId: 'values', chip };
      if (!numeric && !(widget.wells.axis || []).length) return { wellId: 'axis', chip: { field: fieldName } };
      return null;
    }
    if (type === 'slicer') return { wellId: 'field', chip: { field: fieldName } };
    if (type === 'heatmap') {
      if (!(widget.wells.rows || []).length) return { wellId: 'rows', chip: { field: fieldName } };
      if (!(widget.wells.columns || []).length) return { wellId: 'columns', chip: { field: fieldName } };
      if (!(widget.wells.values || []).length && numeric) return { wellId: 'values', chip };
      return null;
    }
    if (type === 'table') return { wellId: 'columns', chip: { field: fieldName } };
    if (type === 'pie') {
      if (numeric && !(widget.wells.values || []).length) return { wellId: 'values', chip };
      if (!numeric && !(widget.wells.legend || []).length) return { wellId: 'legend', chip: { field: fieldName } };
      return null;
    }

    const dimWell = reg.wells.find((w) => w.role === 'dimension');
    const measWell = reg.wells.find((w) => w.role === 'measure' && w.id === 'values');
    if (numeric && measWell) return { wellId: 'values', chip };
    if (!numeric) {
      if (!(widget.wells.axis || []).length) return { wellId: 'axis', chip: { field: fieldName } };
      if (!(widget.wells.legend || []).length) return { wellId: 'legend', chip: { field: fieldName } };
    }
    return null;
  }

  function canAddToWell(widget, wellId, fieldName) {
    const reg = getRegistry(widget.type);
    const def = reg.wells.find((w) => w.id === wellId);
    if (!def) return false;
    const arr = widget.wells[wellId] || [];
    if (def.max === 1 && arr.length >= 1) return false;
    if (arr.some((c) => (typeof c === 'string' ? c : c.field) === fieldName)) return false;
    const type = widget.type || 'bar';
    if (CART_TYPES.includes(type)) {
      if (wellId === 'legend' && wellField(widget.wells.axis, 0) === fieldName) return false;
      if (wellId === 'axis' && wellField(widget.wells.legend, 0) === fieldName) return false;
    }
    return true;
  }

  function addChipToWell(widget, wellId, chip) {
    if (!canAddToWell(widget, wellId, chip.field)) return false;
    const reg = getRegistry(widget.type);
    const def = reg.wells.find((w) => w.id === wellId);
    const arr = widget.wells[wellId] || [];
    if (def.max === 1) {
      widget.wells[wellId] = [chip];
    } else {
      widget.wells[wellId] = [...arr, chip];
    }
    mapWellsToQuery(widget);
    scheduleSave();
    refreshWidget(widget.id);
    renderWells(widget);
    renderFieldsPane(widget);
    return true;
  }

  function removeChipFromWell(widget, wellId, index) {
    const arr = widget.wells[wellId] || [];
    arr.splice(index, 1);
    widget.wells[wellId] = arr;
    mapWellsToQuery(widget);
    scheduleSave();
    refreshWidget(widget.id);
    renderWells(widget);
    renderFieldsPane(widget);
  }

  function fieldInWells(widget, fieldName) {
    const w = widget.wells || {};
    return Object.values(w).some((arr) =>
      (arr || []).some((c) => (typeof c === 'string' ? c : c.field) === fieldName)
    );
  }

  function renderVizGrid() {
    const gridEl = document.getElementById('dashboard-viz-grid');
    if (!gridEl) return;
    gridEl.innerHTML = WIDGET_TYPES.map((t) => `
      <button type="button" title="${t.label}"
        class="dashboard-viz-btn flex flex-col items-center justify-center h-9 rounded border border-slate-200 bg-white hover:border-primary/50 hover:bg-primary-soft/30 transition-colors ${selectedWidgetId && findWidget(selectedWidgetId)?.type === t.type ? 'border-primary bg-primary-soft/40' : ''}"
        data-widget-type="${t.type}">
        <span class="material-symbols-outlined text-[18px] text-slate-600">${t.icon}</span>
      </button>`).join('');

    gridEl.querySelectorAll('[data-widget-type]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const type = btn.dataset.widgetType;
        if (selectedWidgetId) {
          const w = findWidget(selectedWidgetId);
          if (w) {
            w.type = type;
            w.wells = emptyWells(type);
            const meta = WIDGET_TYPES.find((t) => t.type === type);
            if (meta) w.title = meta.label;
            if (type === 'text' && !w.text) {
              w.text = '### Text\nEdit content in the **Formatting** panel on the right.';
            }
            if (!widgetNoData(type)) mapWellsToQuery(w);
            scheduleSave();
            refreshWidget(w.id);
            renderAuthoringPane();
          }
        } else {
          addWidget(type);
        }
      });
    });
  }

  function renderWellChip(widget, wellId, chip, index, role) {
    const field = typeof chip === 'string' ? chip : chip.field;
    const display = chipDisplayLabel(field);
    const agg = typeof chip === 'string' ? 'sum' : (chip.agg || 'sum');
    const aggHtml = role === 'measure'
      ? `<select class="dashboard-chip-agg text-[8px] border-0 bg-transparent font-mono p-0 h-4" data-well="${wellId}" data-idx="${index}">
          ${AGG_OPTIONS.map((o) => `<option value="${o.value}" ${o.value === agg ? 'selected' : ''}>${o.label}</option>`).join('')}
        </select>`
      : '';
    return `
      <div class="dashboard-well-chip inline-flex items-center gap-0.5 max-w-full bg-primary-soft border border-primary/25 rounded px-1.5 py-0.5 text-[9px] font-mono text-slate-800"
           draggable="true" data-field="${field}" data-well="${wellId}" data-idx="${index}">
        <span class="truncate max-w-[72px]" title="${display}">${display}</span>
        ${aggHtml}
        <button type="button" class="dashboard-chip-remove text-slate-400 hover:text-red-500 leading-none" data-well="${wellId}" data-idx="${index}">&times;</button>
      </div>`;
  }

  function renderWells(widget) {
    const container = document.getElementById('dashboard-wells');
    if (!container) return;
    if (!widget) {
      container.innerHTML = '<p class="text-[10px] text-slate-400 font-medium px-1">Select a widget on the canvas to configure field wells.</p>';
      return;
    }
    if (widgetNoData(widget.type)) {
      container.innerHTML = '<p class="text-[10px] text-slate-400 font-medium px-1">This widget uses the Formatting panel — no field wells.</p>';
      return;
    }
    ensureWidget(widget);
    const reg = getRegistry(widget.type);
    container.innerHTML = reg.wells.map((def) => {
      const chips = widget.wells[def.id] || [];
      const chipsHtml = chips.map((c, i) => renderWellChip(widget, def.id, c, i, def.role)).join('');
      return `
        <div class="mb-2" data-well-block="${def.id}">
          <div class="text-[8px] font-black uppercase tracking-widest text-slate-400 mb-0.5">${def.label}</div>
          <div class="dashboard-well-drop min-h-[28px] rounded border border-dashed border-slate-200 bg-slate-50/80 p-1 flex flex-wrap gap-1 items-center"
               data-well-id="${def.id}" data-role="${def.role}">
            ${chipsHtml || '<span class="text-[9px] text-slate-400 italic px-1">Add data fields here</span>'}
          </div>
        </div>`;
    }).join('');

    container.querySelectorAll('.dashboard-well-drop').forEach((zone) => {
      zone.addEventListener('dragover', (e) => {
        e.preventDefault();
        zone.classList.add('border-primary', 'bg-primary-soft/20');
      });
      zone.addEventListener('dragleave', () => {
        zone.classList.remove('border-primary', 'bg-primary-soft/20');
      });
      zone.addEventListener('drop', (e) => {
        e.preventDefault();
        zone.classList.remove('border-primary', 'bg-primary-soft/20');
        const raw = e.dataTransfer.getData('application/x-spore-field');
        if (!raw) return;
        try {
          const { field, dtype, agg } = JSON.parse(raw);
          const wellId = zone.dataset.wellId;
          const role = zone.dataset.role;
          const chip = role === 'measure'
            ? { field, agg: agg || defaultAggForField(field, schemaForStream(widget.source?.ref)) }
            : { field };
          addChipToWell(widget, wellId, chip);
        } catch (_) { /* ignore */ }
      });
    });

    container.querySelectorAll('.dashboard-chip-remove').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        removeChipFromWell(widget, btn.dataset.well, parseInt(btn.dataset.idx, 10));
      });
    });

    container.querySelectorAll('.dashboard-chip-agg').forEach((sel) => {
      sel.addEventListener('change', () => {
        const wellId = sel.dataset.well;
        const idx = parseInt(sel.dataset.idx, 10);
        const arr = widget.wells[wellId];
        if (arr && arr[idx]) {
          if (typeof arr[idx] === 'string') arr[idx] = { field: arr[idx], agg: sel.value };
          else arr[idx].agg = sel.value;
          mapWellsToQuery(widget);
          scheduleSave();
          refreshWidget(widget.id);
        }
      });
    });
  }

  function renderFieldsPane(widget) {
    const list = document.getElementById('dashboard-fields-list');
    const search = document.getElementById('dashboard-fields-search');
    if (!list) return;
    const sourceRef = pageSourceRef() || widget?.source?.ref;
    if (widget && widgetNoData(widget.type)) {
      list.innerHTML = '<p class="text-[10px] text-slate-400 font-medium px-1">This widget type does not use data fields.</p>';
      return;
    }
    if (!sourceRef) {
      list.innerHTML = '<p class="text-[10px] text-slate-400 font-medium px-1">Pick a data source for this page above.</p>';
      return;
    }

    const schema = schemaForStream(sourceRef);
    const q = (search?.value || '').trim().toLowerCase();
    const filteredCols = schema.filter((s) => !q || s.name.toLowerCase().includes(q));
    const measures = buildMeasures(schema, q);

    if (!filteredCols.length && !measures.length) {
      list.innerHTML = '<p class="text-[10px] text-slate-400 px-1">No fields match.</p>';
      return;
    }

    const canCheck = Boolean(widget && !widgetNoData(widget.type));
    const esc = (s) => String(s ?? '').replace(/"/g, '&quot;');

    let html = '';
    if (measures.length) {
      html += '<div class="dashboard-fields-section mb-2.5">';
      html += '<div class="text-[8px] font-black uppercase tracking-widest text-slate-400 px-1 mb-1">Measures</div>';
      html += measures.map((m) => `
        <div class="dashboard-measure-row flex items-center gap-1.5 rounded px-1 py-0.5 hover:bg-slate-50 cursor-pointer group"
             data-field="${esc(m.field)}" data-dtype="${esc(m.dtype)}" data-agg="${esc(m.agg)}" data-label="${esc(m.label)}">
          <span class="material-symbols-outlined text-[14px] text-primary shrink-0">functions</span>
          <span class="dashboard-measure-chip flex-1 text-[10px] font-mono text-slate-700 truncate" draggable="true"
                data-field="${esc(m.field)}" data-dtype="${esc(m.dtype)}" data-agg="${esc(m.agg)}"
                title="${esc(m.label)}">${esc(m.label)}</span>
        </div>`).join('');
      html += '</div>';
    }

    if (filteredCols.length) {
      html += '<div class="dashboard-fields-section">';
      html += '<div class="text-[8px] font-black uppercase tracking-widest text-slate-400 px-1 mb-1">Columns</div>';
      html += filteredCols.map((col) => {
        const numeric = isNumericType(col.type);
        const icon = numeric ? 'tag' : 'text_fields';
        const checked = canCheck && fieldInWells(widget, col.name) ? 'checked' : '';
        const checkHtml = canCheck
          ? `<input type="checkbox" class="dashboard-field-check rounded border-slate-300 text-primary focus:ring-primary shrink-0" ${checked}
                   data-field="${esc(col.name)}" data-dtype="${esc(col.type)}" />`
          : '';
        return `
          <label class="dashboard-field-row flex items-center gap-1.5 rounded px-1 py-0.5 hover:bg-slate-50 cursor-pointer group"
                 data-field-name="${esc(col.name)}">
            ${checkHtml}
            <span class="material-symbols-outlined text-[14px] text-slate-400 shrink-0">${icon}</span>
            <span class="dashboard-field-chip flex-1 text-[10px] font-mono text-slate-700 truncate" draggable="true"
                  data-field="${esc(col.name)}" data-dtype="${esc(col.type)}" title="${esc(col.type)}">${esc(col.name)}</span>
          </label>`;
      }).join('');
      html += '</div>';
    }

    list.innerHTML = html;

    const attachDrag = (el, extra) => {
      el.addEventListener('dragstart', (e) => {
        const payload = JSON.stringify({
          field: el.dataset.field,
          dtype: el.dataset.dtype,
          ...(extra || {}),
        });
        e.dataTransfer.setData('application/x-spore-field', payload);
        e.dataTransfer.effectAllowed = 'copy';
      });
    };

    list.querySelectorAll('.dashboard-field-chip').forEach((chip) => attachDrag(chip));
    list.querySelectorAll('.dashboard-measure-chip').forEach((chip) => {
      attachDrag(chip, { agg: chip.dataset.agg });
    });

    if (canCheck) {
      list.querySelectorAll('.dashboard-measure-row').forEach((row) => {
        row.addEventListener('click', () => {
          addMeasure(widget, row.dataset.field, row.dataset.agg);
        });
      });
    }

    if (!canCheck) return;

    list.querySelectorAll('.dashboard-field-check').forEach((cb) => {
      cb.addEventListener('change', () => {
        const field = cb.dataset.field;
        const dtype = cb.dataset.dtype;
        if (cb.checked) {
          const target = defaultWellForField(widget, field, dtype);
          if (target) {
            const chip = target.chip.field ? target.chip : { field, agg: defaultAggForField(field, schema) };
            if (!chip.field) chip.field = field;
            addChipToWell(widget, target.wellId, chip);
          } else {
            cb.checked = false;
          }
        } else {
          Object.keys(widget.wells).forEach((wellId) => {
            const arr = widget.wells[wellId] || [];
            const idx = arr.findIndex((c) => (typeof c === 'string' ? c : c.field) === field);
            if (idx >= 0) removeChipFromWell(widget, wellId, idx);
          });
        }
      });
    });
  }

  async function renderSettingsPane(widget) {
    const pane = document.getElementById('dashboard-settings-pane');
    if (!pane) return;
    if (!widget) {
      pane.classList.add('hidden');
      return;
    }
    pane.classList.remove('hidden');
    await fetchDatasets();
    const titleIn = document.getElementById('dashboard-cfg-title');
    const streamSel = document.getElementById('dashboard-cfg-stream');
    const palSel = document.getElementById('dashboard-cfg-palette');
    const sourceWrap = document.getElementById('dashboard-cfg-source-wrap');
    const textWrap = document.getElementById('dashboard-cfg-text-wrap');
    const textIn = document.getElementById('dashboard-cfg-text');
    const isText = widget.type === 'text';
    const isButton = widget.type === 'button';
    const isParameter = widget.type === 'parameter';
    const noSource = isText || isButton || isParameter;

    sourceWrap?.classList.add('hidden');
    textWrap?.classList.toggle('hidden', !isText);
    palSel?.closest('label')?.classList.toggle('hidden', noSource);

    if (titleIn) titleIn.value = widget.title || '';
    if (textIn) textIn.value = widget.text || '';

    if (streamSel && !noSource) {
      const all = Object.values(datasetsCache);
      const streamEntries = all.filter((d) => d.is_stream);
      const fileEntries = all.filter((d) => !d.is_stream);
      const esc = (s) => String(s).replace(/"/g, '&quot;');
      let html = '<option value="">—</option>';
      if (streamEntries.length) {
        html += '<optgroup label="Streams">';
        streamEntries.forEach((d) => {
          const fmt = d.format ? ` (${d.format})` : '';
          html += `<option value="${esc(d.ref)}" ${widget.source?.ref === d.ref ? 'selected' : ''}>${esc(d.label)}${fmt}</option>`;
        });
        html += '</optgroup>';
      }
      if (fileEntries.length) {
        html += '<optgroup label="Files">';
        fileEntries.forEach((d) => {
          const fmt = d.format ? ` (${d.format})` : '';
          html += `<option value="${esc(d.ref)}" ${widget.source?.ref === d.ref ? 'selected' : ''}>${esc(d.label)}${fmt}</option>`;
        });
        html += '</optgroup>';
      }
      streamSel.innerHTML = html;
      const selectedOpt = streamSel.options[streamSel.selectedIndex];
      streamSel.title = selectedOpt ? (selectedOpt.textContent || selectedOpt.value || '') : '';
    }
    if (palSel && !noSource) palSel.value = widget.style?.palette || 'default';

    const onStream = async () => {
      widget.source.ref = streamSel.value || '';
      const opt = streamSel.options[streamSel.selectedIndex];
      streamSel.title = opt ? (opt.textContent || opt.value || '') : '';
      await fetchDatasets();
      await fetchRelations();
      scheduleSave();
      renderFieldsPane(widget);
      renderFiltersCard(widget);
      renderAdvancedCard(widget);
      renderControlledByCard(widget);
      refreshWidget(widget.id);
    };
    if (streamSel && !noSource) {
      streamSel.removeEventListener('change', streamSel._sporeHandler);
      const handler = onStream;
      streamSel._sporeHandler = handler;
      streamSel.addEventListener('change', handler);
    }

    titleIn?.removeEventListener('change', titleIn._sporeHandler);
    titleIn._sporeHandler = () => {
      widget.title = titleIn.value || widget.title;
      scheduleSave();
      const titleEl = document.querySelector(`[gs-id="${widget.id}"] .font-black`);
      if (titleEl) titleEl.textContent = widget.title;
      if (widget.type === 'button') refreshWidget(widget.id);
    };
    titleIn?.addEventListener('change', titleIn._sporeHandler);

    palSel?.removeEventListener('change', palSel._sporeHandler);
    palSel._sporeHandler = () => {
      widget.style.palette = palSel.value;
      scheduleSave();
      refreshWidget(widget.id);
    };
    palSel?.addEventListener('change', palSel._sporeHandler);

    textIn?.removeEventListener('input', textIn._sporeHandler);
    textIn._sporeHandler = () => {
      widget.text = textIn.value;
      scheduleSave();
      refreshWidget(widget.id);
    };
    textIn?.addEventListener('input', textIn._sporeHandler);
  }

  function renderNavCard(widget) {
    const host = document.getElementById('dashboard-cfg-nav');
    if (!host) return;
    if (!widget || widget.type !== 'button') {
      host.innerHTML = '';
      return;
    }
    if (!widget.nav || typeof widget.nav !== 'object') widget.nav = { target: '' };
    const esc = (s) => String(s ?? '').replace(/"/g, '&quot;');
    const opts = ['<option value="">— Select page —</option>']
      .concat(
        (dashboardState.pages || []).map(
          (p) => `<option value="${esc(p.id)}" ${widget.nav.target === p.id ? 'selected' : ''}>${esc(p.name)}</option>`
        )
      )
      .join('');
    host.innerHTML = `
      <div class="text-[8px] font-black uppercase tracking-widest text-slate-400 mb-1">Navigation</div>
      <label class="block mb-1">
        <span class="text-[8px] font-black uppercase tracking-widest text-slate-400">Go to page</span>
        <select id="nav-target" class="mt-0.5 w-full rounded-lg border-slate-200 text-[11px] font-mono h-8 px-2">${opts}</select>
      </label>
      <p class="text-[9px] text-slate-400 italic leading-snug">Button label comes from the Title field above. Click the button in View mode to jump to the chosen page.</p>`;

    host.querySelector('#nav-target')?.addEventListener('change', (e) => {
      widget.nav.target = e.target.value;
      scheduleSave();
      refreshWidget(widget.id);
    });
  }

  function controllerWidgets(excludeId) {
    return currentWidgets().filter(
      (w) => w.id !== excludeId && (w.type === 'slicer' || CLICK_FILTER_TYPES.includes(w.type))
    );
  }

  function controllerLabel(w) {
    const field = w.type === 'slicer' ? wellField(w.wells?.field, 0) : (w.encoding?.x || '');
    const base = w.title || w.type;
    return field ? `${base} · ${field}` : base;
  }

  function coerceFilterValue(value, fieldName, schema) {
    if (value === '' || value === null || value === undefined) return value;
    const col = (schema || []).find((s) => s.name === fieldName);
    if (col && isNumericType(col.type) && value !== '' && !Number.isNaN(Number(value))) {
      return Number(value);
    }
    return value;
  }

  function renderFiltersCard(widget) {
    const host = document.getElementById('dashboard-cfg-filters');
    if (!host) return;
    if (!widget || widgetNoData(widget.type) || !widget.source?.ref) {
      host.innerHTML = '';
      return;
    }
    const schema = schemaForStream(widget.source.ref);
    const esc = (s) => String(s ?? '').replace(/"/g, '&quot;');
    const fieldOpts = (sel) =>
      schema.map((s) => `<option value="${esc(s.name)}" ${s.name === sel ? 'selected' : ''}>${esc(s.name)}</option>`).join('');
    const opOpts = (sel) =>
      FILTER_OPS.map((o) => `<option value="${o.value}" ${o.value === sel ? 'selected' : ''}>${o.label}</option>`).join('');
    const rows = (widget.filters || []).map((f, i) => `
      <div class="flex items-center gap-1 mb-1" data-filter-row="${i}">
        <select class="flt-field flex-1 rounded border-slate-200 text-[9px] font-mono h-6 px-1 min-w-0" data-idx="${i}"><option value="">field…</option>${fieldOpts(f.field)}</select>
        <select class="flt-op rounded border-slate-200 text-[9px] font-mono h-6 px-1" data-idx="${i}">${opOpts(f.op || 'eq')}</select>
        <input class="flt-val w-12 rounded border-slate-200 text-[9px] font-mono h-6 px-1 min-w-0" data-idx="${i}" value="${esc(f.value)}" placeholder="value" />
        <button type="button" class="flt-del text-slate-400 hover:text-red-500 text-sm leading-none" data-idx="${i}">&times;</button>
      </div>`).join('');
    host.innerHTML = `
      <div class="text-[8px] font-black uppercase tracking-widest text-slate-400 mb-1">Filters</div>
      ${rows || '<p class="text-[9px] text-slate-400 italic mb-1">No row filters.</p>'}
      <button type="button" id="flt-add" class="text-[9px] font-bold text-primary hover:underline">+ Add filter</button>`;

    const commit = () => {
      mapWellsToQuery(widget);
      scheduleSave();
      refreshWidget(widget.id);
    };

    host.querySelector('#flt-add')?.addEventListener('click', () => {
      widget.filters = [...(widget.filters || []), { field: '', op: 'eq', value: '' }];
      renderFiltersCard(widget);
    });
    host.querySelectorAll('.flt-field').forEach((sel) => {
      sel.addEventListener('change', () => {
        const i = parseInt(sel.dataset.idx, 10);
        widget.filters[i].field = sel.value;
        widget.filters[i].value = coerceFilterValue(widget.filters[i].value, sel.value, schema);
        commit();
      });
    });
    host.querySelectorAll('.flt-op').forEach((sel) => {
      sel.addEventListener('change', () => {
        const i = parseInt(sel.dataset.idx, 10);
        widget.filters[i].op = sel.value;
        commit();
      });
    });
    host.querySelectorAll('.flt-val').forEach((inp) => {
      inp.addEventListener('change', () => {
        const i = parseInt(inp.dataset.idx, 10);
        widget.filters[i].value = coerceFilterValue(inp.value, widget.filters[i].field, schema);
        commit();
      });
    });
    host.querySelectorAll('.flt-del').forEach((btn) => {
      btn.addEventListener('click', () => {
        const i = parseInt(btn.dataset.idx, 10);
        widget.filters.splice(i, 1);
        renderFiltersCard(widget);
        commit();
      });
    });
  }

  function renderAdvancedCard(widget) {
    const host = document.getElementById('dashboard-cfg-advanced');
    if (!host) return;
    if (!widget || widgetNoData(widget.type) || !widget.source?.ref) {
      host.innerHTML = '';
      return;
    }
    const schema = schemaForStream(widget.source.ref);
    const esc = (s) => String(s ?? '').replace(/"/g, '&quot;');
    const sortField = widget.sort?.field || '';
    const sortDir = widget.sort?.dir === 'desc' ? 'desc' : 'asc';
    const limit = widget.transform?.limit || 500;
    const fieldOpts = schema
      .map((s) => `<option value="${esc(s.name)}" ${s.name === sortField ? 'selected' : ''}>${esc(s.name)}</option>`)
      .join('');
    host.innerHTML = `
      <div class="text-[8px] font-black uppercase tracking-widest text-slate-400 mb-1">Advanced</div>
      <div class="flex items-center gap-1 mb-1">
        <select id="adv-sort-field" class="flex-1 rounded border-slate-200 text-[9px] font-mono h-6 px-1 min-w-0"><option value="">Sort by…</option>${fieldOpts}</select>
        <select id="adv-sort-dir" class="rounded border-slate-200 text-[9px] font-mono h-6 px-1">
          <option value="asc" ${sortDir === 'asc' ? 'selected' : ''}>Asc</option>
          <option value="desc" ${sortDir === 'desc' ? 'selected' : ''}>Desc</option>
        </select>
      </div>
      <label class="flex items-center gap-1">
        <span class="text-[9px] font-bold text-slate-500">Limit</span>
        <input id="adv-limit" type="number" min="1" max="10000" value="${limit}" class="w-16 rounded border-slate-200 text-[9px] font-mono h-6 px-1" />
      </label>`;

    const commit = () => {
      mapWellsToQuery(widget);
      scheduleSave();
      refreshWidget(widget.id);
    };
    host.querySelector('#adv-sort-field')?.addEventListener('change', (e) => {
      widget.sort = { ...widget.sort, field: e.target.value };
      commit();
    });
    host.querySelector('#adv-sort-dir')?.addEventListener('change', (e) => {
      widget.sort = { ...widget.sort, dir: e.target.value };
      commit();
    });
    host.querySelector('#adv-limit')?.addEventListener('change', (e) => {
      const v = parseInt(e.target.value, 10);
      if (!Number.isNaN(v) && v > 0) {
        widget.transform.limit = Math.min(v, 10000);
        commit();
      }
    });
  }

  function renderControlledByCard(_widget) {
    const host = document.getElementById('dashboard-cfg-controlledby');
    if (host) host.innerHTML = '';
  }

  function renderTableCard(widget) {
    const host = document.getElementById('dashboard-cfg-table');
    if (!host) return;
    if (!widget || widget.type !== 'table') {
      host.innerHTML = '';
      return;
    }
    ensureWidget(widget);
    const tableStyle = widget.style.table || { groupBy: '', dataBars: [], rules: [] };
    const cols = widget.encoding?.columns?.length ? widget.encoding.columns : [];
    const esc = (s) => String(s ?? '').replace(/"/g, '&quot;');
    const groupOpts = ['<option value="">— none —</option>']
      .concat(cols.map((c) => `<option value="${esc(c)}" ${tableStyle.groupBy === c ? 'selected' : ''}>${esc(c)}</option>`))
      .join('');
    const barChecks = cols.map((c) => {
      const checked = (tableStyle.dataBars || []).includes(c) ? 'checked' : '';
      return `<label class="flex items-center gap-1 text-[9px] font-mono text-slate-600"><input type="checkbox" class="tbl-bar" data-col="${esc(c)}" ${checked} /> ${esc(c)}</label>`;
    }).join('');
    const rules = (tableStyle.rules || []).map((r, i) => `
      <div class="grid grid-cols-6 gap-1 mb-1 items-center" data-rule="${i}">
        <select class="rule-col col-span-2 rounded border-slate-200 text-[9px] h-6 px-1">${cols.map((c) => `<option value="${esc(c)}" ${r.col === c ? 'selected' : ''}>${esc(c)}</option>`).join('')}</select>
        <select class="rule-kind rounded border-slate-200 text-[9px] h-6 px-1">
          <option value="text" ${r.kind === 'text' ? 'selected' : ''}>text</option>
          <option value="cell" ${r.kind === 'cell' ? 'selected' : ''}>cell</option>
          <option value="dot" ${r.kind === 'dot' ? 'selected' : ''}>dot</option>
        </select>
        <select class="rule-op rounded border-slate-200 text-[9px] h-6 px-1">
          <option value="gt" ${r.op === 'gt' ? 'selected' : ''}>&gt;</option>
          <option value="lt" ${r.op === 'lt' ? 'selected' : ''}>&lt;</option>
          <option value="between" ${r.op === 'between' ? 'selected' : ''}>between</option>
        </select>
        <input class="rule-val rounded border-slate-200 text-[9px] h-6 px-1" value="${esc(r.value)}" />
        <input class="rule-color rounded border-slate-200 text-[9px] h-6 px-1" value="${esc(r.color || '#00A36C')}" />
      </div>`).join('');
    host.innerHTML = `
      <div class="text-[8px] font-black uppercase tracking-widest text-slate-400 mb-1">Table format</div>
      <label class="block mb-1"><span class="text-[8px] font-black uppercase tracking-widest text-slate-400">Group by</span>
        <select id="tbl-group" class="mt-0.5 w-full rounded-lg border-slate-200 text-[11px] font-mono h-8 px-2">${groupOpts}</select></label>
      <div class="mb-1"><span class="text-[8px] font-black uppercase tracking-widest text-slate-400">Data bars</span><div class="mt-1 flex flex-wrap gap-2">${barChecks || '<span class="text-[9px] text-slate-400 italic">Add columns first</span>'}</div></div>
      <div class="mb-1"><span class="text-[8px] font-black uppercase tracking-widest text-slate-400">Conditional rules</span>${rules}</div>
      <button type="button" id="tbl-rule-add" class="text-[9px] font-bold text-primary hover:underline">+ Add rule</button>`;
    const commit = () => { scheduleSave(); refreshWidget(widget.id); };
    host.querySelector('#tbl-group')?.addEventListener('change', (e) => {
      widget.style.table.groupBy = e.target.value;
      commit();
    });
    host.querySelectorAll('.tbl-bar').forEach((cb) => {
      cb.addEventListener('change', () => {
        const set = new Set(tableStyle.dataBars || []);
        if (cb.checked) set.add(cb.dataset.col);
        else set.delete(cb.dataset.col);
        widget.style.table.dataBars = [...set];
        commit();
      });
    });
    host.querySelector('#tbl-rule-add')?.addEventListener('click', () => {
      widget.style.table.rules = [...(tableStyle.rules || []), { col: cols[0] || '', kind: 'dot', op: 'gt', value: 0, color: '#00A36C' }];
      renderTableCard(widget);
    });
    host.querySelectorAll('[data-rule]').forEach((row) => {
      const i = parseInt(row.dataset.rule, 10);
      const syncRule = () => {
        widget.style.table.rules[i] = {
          col: row.querySelector('.rule-col')?.value,
          kind: row.querySelector('.rule-kind')?.value,
          op: row.querySelector('.rule-op')?.value,
          value: row.querySelector('.rule-val')?.value,
          color: row.querySelector('.rule-color')?.value,
        };
        commit();
      };
      row.querySelectorAll('select, input').forEach((el) => el.addEventListener('change', syncRule));
    });
  }

  function renderKpiCard(widget) {
    const host = document.getElementById('dashboard-cfg-kpi');
    if (!host) return;
    if (!widget || widget.type !== 'kpi') {
      host.innerHTML = '';
      return;
    }
    ensureWidget(widget);
    const k = widget.style.kpi || {};
    const esc = (s) => String(s ?? '').replace(/"/g, '&quot;');
    host.innerHTML = `
      <div class="text-[8px] font-black uppercase tracking-widest text-slate-400 mb-1">KPI options</div>
      <label class="block mb-1"><span class="text-[8px] font-black uppercase tracking-widest text-slate-400">Target value</span>
        <input id="kpi-target" type="number" class="mt-0.5 w-full rounded-lg border-slate-200 text-[11px] font-mono h-8 px-2" value="${esc(k.target)}" /></label>
      <label class="block mb-1"><span class="text-[8px] font-black uppercase tracking-widest text-slate-400">Format</span>
        <select id="kpi-format" class="mt-0.5 w-full rounded-lg border-slate-200 text-[11px] font-mono h-8 px-2">
          <option value="number" ${k.format === 'number' ? 'selected' : ''}>Number</option>
          <option value="currency" ${!k.format || k.format === 'currency' ? 'selected' : ''}>Currency</option>
          <option value="percent" ${k.format === 'percent' ? 'selected' : ''}>Percent</option>
        </select></label>
      <label class="block mb-1"><span class="text-[8px] font-black uppercase tracking-widest text-slate-400">Good direction</span>
        <select id="kpi-dir" class="mt-0.5 w-full rounded-lg border-slate-200 text-[11px] font-mono h-8 px-2">
          <option value="up" ${k.goodDirection !== 'down' ? 'selected' : ''}>Higher is better</option>
          <option value="down" ${k.goodDirection === 'down' ? 'selected' : ''}>Lower is better</option>
        </select></label>
      <label class="flex items-center gap-2 text-[10px] text-slate-600"><input id="kpi-delta" type="checkbox" ${k.showDelta !== false ? 'checked' : ''} /> Show variance pill</label>`;
    const commit = () => { scheduleSave(); refreshWidget(widget.id); };
    host.querySelector('#kpi-target')?.addEventListener('change', (e) => { widget.style.kpi.target = e.target.value; commit(); });
    host.querySelector('#kpi-format')?.addEventListener('change', (e) => { widget.style.kpi.format = e.target.value; commit(); });
    host.querySelector('#kpi-dir')?.addEventListener('change', (e) => { widget.style.kpi.goodDirection = e.target.value; commit(); });
    host.querySelector('#kpi-delta')?.addEventListener('change', (e) => { widget.style.kpi.showDelta = e.target.checked; commit(); });
  }

  function renderMapScopeCard(widget) {
    const host = document.getElementById('dashboard-cfg-map');
    if (!host) return;
    if (!widget || widget.type !== 'map') {
      host.innerHTML = '';
      return;
    }
    ensureWidget(widget);
    const scope = widget.style.mapScope || 'world';
    const options = Object.entries(MAP_SCOPES)
      .map(([key, def]) => `<option value="${key}" ${scope === key ? 'selected' : ''}>${def.label}</option>`)
      .join('');
    host.innerHTML = `
      <div class="text-[8px] font-black uppercase tracking-widest text-slate-400 mb-1">Map scope</div>
      <select id="map-scope" class="w-full rounded-lg border-slate-200 text-[11px] font-mono h-8 px-2">
        ${options}
      </select>
      <p class="text-[9px] text-slate-400 italic leading-snug mt-1">Scroll or use the +/− buttons on the map to zoom; drag to pan.</p>`;
    host.querySelector('#map-scope')?.addEventListener('change', (e) => {
      widget.style.mapScope = e.target.value;
      scheduleSave();
      refreshWidget(widget.id);
    });
  }

  function renderParameterCard(widget) {
    const host = document.getElementById('dashboard-cfg-parameter');
    if (!host) return;
    if (!widget || widget.type !== 'parameter') {
      host.innerHTML = '';
      return;
    }
    ensureWidget(widget);
    const p = widget.param || {};
    const esc = (s) => String(s ?? '').replace(/"/g, '&quot;');
    host.innerHTML = `
      <div class="text-[8px] font-black uppercase tracking-widest text-slate-400 mb-1">Parameter</div>
      <label class="block mb-1"><span class="text-[8px] font-black uppercase tracking-widest text-slate-400">Name</span>
        <input id="param-name" class="mt-0.5 w-full rounded-lg border-slate-200 text-[11px] font-mono h-8 px-2" value="${esc(p.name)}" /></label>
      <div class="grid grid-cols-3 gap-1 mb-1">
        <label><span class="text-[8px] font-black uppercase tracking-widest text-slate-400">Min</span>
          <input id="param-min" type="number" class="mt-0.5 w-full rounded border-slate-200 text-[10px] h-6 px-1" value="${esc(p.min)}" /></label>
        <label><span class="text-[8px] font-black uppercase tracking-widest text-slate-400">Max</span>
          <input id="param-max" type="number" class="mt-0.5 w-full rounded border-slate-200 text-[10px] h-6 px-1" value="${esc(p.max)}" /></label>
        <label><span class="text-[8px] font-black uppercase tracking-widest text-slate-400">Default</span>
          <input id="param-val" type="number" class="mt-0.5 w-full rounded border-slate-200 text-[10px] h-6 px-1" value="${esc(p.value)}" /></label>
      </div>`;
    const commit = () => { scheduleSave(); refreshWidget(widget.id); };
    host.querySelector('#param-name')?.addEventListener('change', (e) => { widget.param.name = e.target.value.trim() || widget.param.name; commit(); });
    host.querySelector('#param-min')?.addEventListener('change', (e) => { widget.param.min = Number(e.target.value); commit(); });
    host.querySelector('#param-max')?.addEventListener('change', (e) => { widget.param.max = Number(e.target.value); commit(); });
    host.querySelector('#param-val')?.addEventListener('change', (e) => {
      widget.param.value = Number(e.target.value);
      dashboardParams[widget.param.name] = widget.param.value;
      commit();
      refreshParamSubscribers(widget.param.name);
    });
  }

  function renderScaleByParamCard(widget) {
    const host = document.getElementById('dashboard-cfg-scale');
    if (!host) return;
    if (!widget || widgetNoData(widget.type) || widget.type === 'parameter') {
      host.innerHTML = '';
      return;
    }
    const names = listParamNames();
    if (!names.length) {
      host.innerHTML = '';
      return;
    }
    const esc = (s) => String(s ?? '').replace(/"/g, '&quot;');
    const cur = widget.style?.scaleByParam || '';
    host.innerHTML = `
      <div class="text-[8px] font-black uppercase tracking-widest text-slate-400 mb-1">What-if scaling</div>
      <select id="scale-param" class="w-full rounded-lg border-slate-200 text-[11px] font-mono h-8 px-2">
        <option value="">— none —</option>
        ${names.map((n) => `<option value="${esc(n)}" ${cur === n ? 'selected' : ''}>${esc(n)}</option>`).join('')}
      </select>`;
    host.querySelector('#scale-param')?.addEventListener('change', (e) => {
      widget.style.scaleByParam = e.target.value;
      scheduleSave();
      refreshWidget(widget.id);
    });
  }

  function renderAuthoringPane() {
    const widget = selectedWidgetId ? findWidget(selectedWidgetId) : null;
    renderPageSourcePicker();
    renderVizGrid();
    renderWells(widget);
    renderFieldsPane(widget);
    renderSettingsPane(widget);
    renderNavCard(widget);
    renderTableCard(widget);
    renderKpiCard(widget);
    renderMapScopeCard(widget);
    renderParameterCard(widget);
    renderScaleByParamCard(widget);
    renderFiltersCard(widget);
    renderAdvancedCard(widget);
    renderControlledByCard(widget);
    updateCrossFilterCues();
  }

  function buildWidgetElement(widget) {
    const item = document.createElement('div');
    item.className = 'grid-stack-item';
    item.setAttribute('gs-id', widget.id);
    item.setAttribute('gs-x', String(widget.layout?.x ?? 0));
    item.setAttribute('gs-y', String(widget.layout?.y ?? 0));
    item.setAttribute('gs-w', String(widget.layout?.w ?? 4));
    item.setAttribute('gs-h', String(widget.layout?.h ?? 2));

    // Navigation buttons render without the standard card chrome so they look
    // like a clean nav control. A floating delete affordance shows in Edit mode.
    if (widget.type === 'button') {
      const content = document.createElement('div');
      content.className = 'grid-stack-item-content rounded-xl flex flex-col overflow-hidden cursor-pointer relative bg-transparent';
      const actions = document.createElement('div');
      actions.className = 'dashboard-widget-actions absolute top-1 right-1 z-10 flex items-center gap-0.5';
      actions.innerHTML = `
        <button type="button" data-action="delete" class="p-1 rounded bg-white/90 border border-slate-200 hover:bg-red-50 text-red-400" title="Delete"><span class="material-symbols-outlined text-[13px]">close</span></button>`;
      const body = document.createElement('div');
      body.className = 'flex-1 min-h-0 p-1';
      body.setAttribute('data-widget-body', widget.id);
      content.appendChild(actions);
      content.appendChild(body);
      item.appendChild(content);
      content.addEventListener('click', (e) => {
        if (e.target.closest('[data-action]')) return;
        selectWidget(widget.id);
      });
      actions.querySelector('[data-action="delete"]').addEventListener('click', (e) => {
        e.stopPropagation();
        removeWidget(widget.id);
      });
      return item;
    }

    // Text widgets: no header bar — body fills the card; delete on hover.
    if (widget.type === 'text') {
      const content = document.createElement('div');
      content.className = 'grid-stack-item-content group rounded-xl border border-slate-200/60 bg-white shadow-sm flex flex-col overflow-hidden cursor-pointer relative';
      const actions = document.createElement('div');
      actions.className = 'dashboard-widget-actions absolute top-1 right-1 z-10 flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity';
      actions.innerHTML = `
        <button type="button" data-action="delete" class="p-1 rounded bg-white/90 border border-slate-200/60 hover:bg-red-50 text-red-400" title="Delete"><span class="material-symbols-outlined text-[13px]">close</span></button>`;
      const body = document.createElement('div');
      body.className = 'flex-1 min-h-0';
      body.setAttribute('data-widget-body', widget.id);
      content.appendChild(actions);
      content.appendChild(body);
      item.appendChild(content);
      content.addEventListener('click', (e) => {
        if (e.target.closest('[data-action]')) return;
        selectWidget(widget.id);
      });
      actions.querySelector('[data-action="delete"]').addEventListener('click', (e) => {
        e.stopPropagation();
        removeWidget(widget.id);
      });
      return item;
    }

    const content = document.createElement('div');
    content.className = 'grid-stack-item-content group rounded-xl border border-slate-200/60 bg-white shadow-sm flex flex-col overflow-hidden cursor-pointer';

    const header = document.createElement('div');
    header.className = 'flex items-center justify-between px-2.5 py-1 shrink-0 min-h-0';
    const snapshotBtn = isChartWidgetType(widget.type)
      ? `<button type="button" data-action="snapshot" class="p-0.5 rounded hover:bg-slate-100 text-slate-400" title="Copy chart as PNG"><span class="material-symbols-outlined text-[13px]">photo_camera</span></button>`
      : '';
    header.innerHTML = `
      <div class="flex items-center gap-1 min-w-0 flex-1">
        <span class="text-[9px] font-black uppercase tracking-widest text-slate-600 truncate">${widget.title || widget.type}</span>
        <span data-filter-badge="${widget.id}" class="hidden shrink-0"></span>
      </div>
      <div class="flex items-center gap-0.5 dashboard-widget-actions opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
        ${snapshotBtn}
        <button type="button" data-action="refresh" class="p-0.5 rounded hover:bg-slate-100 text-slate-400" title="Refresh"><span class="material-symbols-outlined text-[13px]">refresh</span></button>
        <button type="button" data-action="delete" class="p-0.5 rounded hover:bg-red-50 text-red-400" title="Delete"><span class="material-symbols-outlined text-[13px]">close</span></button>
      </div>`;

    const body = document.createElement('div');
    body.className = 'flex-1 min-h-0 p-1';
    body.setAttribute('data-widget-body', widget.id);

    content.appendChild(header);
    content.appendChild(body);
    item.appendChild(content);

    content.addEventListener('click', (e) => {
      if (e.target.closest('[data-action]')) return;
      selectWidget(widget.id);
    });
    header.querySelector('[data-action="refresh"]').addEventListener('click', (e) => {
      e.stopPropagation();
      refreshWidget(widget.id);
    });
    header.querySelector('[data-action="snapshot"]')?.addEventListener('click', (e) => {
      e.stopPropagation();
      snapshotWidgetPng(widget.id);
    });
    header.querySelector('[data-action="delete"]').addEventListener('click', (e) => {
      e.stopPropagation();
      removeWidget(widget.id);
    });

    return item;
  }

  function syncLayoutFromGrid() {
    if (!grid) return;
    grid.getGridItems().forEach((el) => {
      const id = el.getAttribute('gs-id');
      const w = findWidget(id);
      if (!w) return;
      const node = el.gridstackNode || {};
      w.layout = { x: node.x ?? 0, y: node.y ?? 0, w: node.w ?? 4, h: node.h ?? 2 };
    });
    scheduleSave();
  }

  function renderPageTabs() {
    const host = document.getElementById('dashboard-page-tabs');
    if (!host) return;
    const pages = dashboardState.pages || [];
    host.innerHTML = '';

    pages.forEach((p) => {
      const active = p.id === dashboardState.activePageId;
      const tab = document.createElement('div');
      tab.className = `group/tab inline-flex items-center gap-1 h-7 pl-3 ${editMode && pages.length > 1 ? 'pr-1' : 'pr-3'} rounded-pill border text-[10px] font-black uppercase tracking-widest cursor-pointer transition-colors shrink-0 ${active ? 'bg-primary text-white border-primary shadow-tactile' : 'bg-white text-slate-500 border-slate-200 hover:text-slate-900 hover:border-primary/40'}`;
      tab.title = 'Click to open · double-click to rename';
      const label = document.createElement('span');
      label.className = 'truncate max-w-[140px]';
      label.textContent = p.name;
      tab.appendChild(label);
      tab.addEventListener('click', () => switchPage(p.id));
      tab.addEventListener('dblclick', (e) => {
        e.stopPropagation();
        renamePage(p.id);
      });
      if (editMode && pages.length > 1) {
        const del = document.createElement('button');
        del.type = 'button';
        del.title = 'Delete page';
        del.className = `rounded-full p-0.5 leading-none transition-opacity opacity-0 group-hover/tab:opacity-100 ${active ? 'text-white/80 hover:bg-white/20' : 'text-slate-300 hover:text-red-500'}`;
        del.innerHTML = '<span class="material-symbols-outlined text-[13px] leading-none">close</span>';
        del.addEventListener('click', (e) => {
          e.stopPropagation();
          deletePage(p.id);
        });
        tab.appendChild(del);
      }
      host.appendChild(tab);
    });

    if (editMode) {
      const add = document.createElement('button');
      add.type = 'button';
      add.title = 'Add page';
      add.className = 'inline-flex items-center justify-center h-7 w-7 rounded-pill border border-dashed border-slate-300 text-slate-400 hover:text-primary hover:border-primary/50 transition-colors shrink-0';
      add.innerHTML = '<span class="material-symbols-outlined text-[16px]">add</span>';
      add.addEventListener('click', () => addPage());
      host.appendChild(add);
    }
  }

  function switchPage(id) {
    if (!id || dashboardState.activePageId === id) return;
    dashboardState.activePageId = id;
    selectedWidgetId = null;
    scheduleSave();
    renderGrid();
    renderAuthoringPane();
  }

  function addPage() {
    if (!Array.isArray(dashboardState.pages)) dashboardState.pages = [];
    const page = {
      id: genPageId(),
      name: `Page ${dashboardState.pages.length + 1}`,
      widgets: [],
      layout: { columns: 12 },
      activeSource: '',
    };
    dashboardState.pages.push(page);
    dashboardState.activePageId = page.id;
    selectedWidgetId = null;
    scheduleSave();
    renderGrid();
    renderAuthoringPane();
  }

  function renamePage(id) {
    const page = (dashboardState.pages || []).find((p) => p.id === id);
    if (!page) return;
    const name = window.prompt('Page name', page.name);
    if (name && name.trim()) {
      page.name = name.trim();
      scheduleSave();
      renderPageTabs();
      // Keep nav-button target labels in sync.
      if (selectedWidgetId) renderNavCard(findWidget(selectedWidgetId));
    }
  }

  function deletePage(id) {
    const pages = dashboardState.pages || [];
    if (pages.length <= 1) return;
    const idx = pages.findIndex((p) => p.id === id);
    if (idx < 0) return;
    if (!window.confirm(`Delete "${pages[idx].name}" and all its widgets?`)) return;
    pages.splice(idx, 1);
    if (dashboardState.activePageId === id) {
      dashboardState.activePageId = pages[Math.max(0, idx - 1)].id;
    }
    selectedWidgetId = null;
    scheduleSave();
    renderGrid();
    renderAuthoringPane();
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
    renderPageTabs();
    const widgets = currentWidgets();
    const hasWidgets = widgets.length > 0;
    if (empty) empty.classList.toggle('hidden', hasWidgets);

    widgets.forEach((w) => ensureWidget(w));

    if (!hasWidgets || typeof GridStack === 'undefined') {
      renderAuthoringPane();
      return;
    }

    grid = GridStack.init({
      column: currentPage()?.layout?.columns || 12,
      cellHeight: 60,
      margin: 6,
      float: true,
      disableDrag: !editMode,
      disableResize: !editMode,
      animate: true,
    }, container);

    widgets.forEach((widget) => {
      const el = buildWidgetElement(widget);
      grid.addWidget(el);
      refreshWidget(widget.id);
    });
    updateCrossFilterCues();

    grid.on('change', () => syncLayoutFromGrid());
    if (selectedWidgetId && findWidget(selectedWidgetId)) {
      selectWidget(selectedWidgetId);
    } else {
      renderAuthoringPane();
    }
  }

  function addWidget(type) {
    const page = currentPage();
    if (!page) return;
    const widget = createWidget(type);
    page.widgets.push(widget);
    scheduleSave();
    selectedWidgetId = widget.id;
    renderGrid();
    if (grid) {
      const existing = document.querySelector(`[gs-id="${widget.id}"]`);
      if (!existing) {
        const el = buildWidgetElement(widget);
        grid.addWidget(el);
        refreshWidget(widget.id);
      }
    }
    selectWidget(widget.id);
  }

  function removeWidget(id) {
    const page = currentPage();
    if (!page) return;
    page.widgets = page.widgets.filter((w) => w.id !== id);
    if (chartInstances[id]) {
      chartInstances[id].dispose();
      delete chartInstances[id];
    }
    delete dashboardFilters[id];
    page.widgets.forEach((w) => {
      if ((w.respondsTo || []).includes(id)) {
        w.respondsTo = w.respondsTo.filter((cid) => cid !== id);
      }
    });
    if (selectedWidgetId === id) selectedWidgetId = null;
    scheduleSave();
    renderGrid();
  }

  function setEditMode(on) {
    editMode = on;
    document.getElementById('dashboard-btn-edit')?.classList.toggle('bg-primary', on);
    document.getElementById('dashboard-btn-edit')?.classList.toggle('text-white', on);
    document.getElementById('dashboard-btn-view')?.classList.toggle('bg-primary', !on);
    document.getElementById('dashboard-btn-view')?.classList.toggle('text-white', !on);
    if (grid) {
      if (typeof grid.setStatic === 'function') grid.setStatic(!on);
      else if (typeof grid.enableMove === 'function') {
        grid.enableMove(on);
        grid.enableResize(on);
      }
    }
    document.querySelectorAll('.dashboard-widget-actions').forEach((el) => {
      el.classList.toggle('hidden', !on);
    });
    renderPageTabs();
  }

  function hydrateDashboard(state) {
    _hydrating = true;
    loadState();
    if (state && typeof state === 'object') {
      dashboardState = ensurePages(state);
    }
    const titleEl = document.getElementById('dashboard-header-name');
    if (titleEl) titleEl.textContent = dashboardState.title || window.SPORE_WORKSPACE?.name || 'Dashboard';
    updateHeader();
    fetchRelations().then(() => renderGrid());
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
      await fetchDatasets();
      await fetchRelations();
      if (selectedWidgetId) renderFieldsPane(findWidget(selectedWidgetId));
    } catch (e) {
      console.warn('relation register failed', e);
    }
  }

  function bindControls() {
    document.getElementById('dashboard-btn-add')?.addEventListener('click', () => addWidget('bar'));
    document.getElementById('dashboard-btn-edit')?.addEventListener('click', () => setEditMode(true));
    document.getElementById('dashboard-btn-view')?.addEventListener('click', () => setEditMode(false));
    document.getElementById('dashboard-export-toggle')?.addEventListener('click', (e) => {
      e.stopPropagation();
      toggleExportDropdown();
    });
    document.getElementById('export-dashboard-html')?.addEventListener('click', () => {
      toggleExportDropdown(false);
      exportDashboardHtml();
    });
    document.getElementById('export-dashboard-pdf')?.addEventListener('click', () => {
      toggleExportDropdown(false);
      exportDashboardPdf();
    });
    document.addEventListener('click', (e) => {
      if (!e.target.closest('#dashboard-export-menu')) toggleExportDropdown(false);
    });
    document.getElementById('dashboard-fields-search')?.addEventListener('input', () => {
      const w = selectedWidgetId ? findWidget(selectedWidgetId) : null;
      if (w) renderFieldsPane(w);
    });
    document.querySelectorAll('[data-deck] .deck-header').forEach((header) => {
      header.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          header.click();
        }
      });
    });
  }

  window.hydrateDashboardFromWorkspace = hydrateDashboard;
  window.registerRelationAfterIngest = registerRelationAfterIngest;
  window.getDashboardState = () => dashboardState;
  window.toggleDashboardDeck = toggleDashboardDeck;

  document.addEventListener('DOMContentLoaded', () => {
    bindControls();
    renderVizGrid();
    fetchDatasets().then(() => fetchRelations());
    if (window.SPORE_WORKSPACE_STATE?.dashboard) {
      hydrateDashboard(window.SPORE_WORKSPACE_STATE.dashboard);
    } else {
      hydrateDashboard(null);
    }
  });
})();
