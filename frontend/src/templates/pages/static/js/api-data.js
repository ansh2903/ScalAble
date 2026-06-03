/**
 * API connection request builder (api-data panel).
 */
(() => {
    let _activeConn = null;

    function escapeHtml(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function isApiConnection(conn) {
        if (!conn) return false;
        if (typeof window.resolveDataKind === 'function') {
            return window.resolveDataKind(conn) === 'api';
        }
        const st = String(conn.source_type || '').toLowerCase();
        return st === 'rest_api' || st === 'graphql_api';
    }

    function parseKvTable(tbodyId) {
        const tbody = document.getElementById(tbodyId);
        if (!tbody) return [];
        const out = [];
        tbody.querySelectorAll('tr').forEach((tr) => {
            const inputs = tr.querySelectorAll('input');
            if (inputs.length < 2) return;
            const key = (inputs[0].value || '').trim();
            const value = (inputs[1].value || '').trim();
            if (key) out.push({ key, value });
        });
        return out;
    }

    function setApiTab(tab) {
        ['params', 'headers', 'body', 'auth'].forEach((name) => {
            const pane = document.getElementById(`api-tab-${name}`);
            if (pane) pane.classList.toggle('hidden', name !== tab);
        });
        document.querySelectorAll('.api-tab').forEach((btn) => {
            const on = btn.dataset.apiTab === tab;
            btn.classList.toggle('bg-primary', on);
            btn.classList.toggle('text-white', on);
            btn.classList.toggle('shadow-tactile', on);
            btn.classList.toggle('text-slate-500', !on);
            btn.classList.toggle('hover:text-slate-900', !on);
            btn.classList.toggle('hover:bg-white', !on);
        });
    }

    function setApiResTab(tab) {
        const bodyEl = document.getElementById('api-response-body');
        const headersEl = document.getElementById('api-response-headers');
        if (bodyEl) bodyEl.classList.toggle('hidden', tab !== 'body');
        if (headersEl) headersEl.classList.toggle('hidden', tab !== 'headers');

        document.querySelectorAll('.api-res-tab').forEach((btn) => {
            const on = btn.dataset.apiResTab === tab;
            btn.classList.toggle('bg-primary', on);
            btn.classList.toggle('text-white', on);
            btn.classList.toggle('shadow-tactile', on);
            btn.classList.toggle('text-slate-500', !on);
            btn.classList.toggle('hover:text-slate-900', !on);
            btn.classList.toggle('hover:bg-white', !on);
        });
    }

    function formatBytes(n) {
        const b = Number(n) || 0;
        if (b < 1024) return `${b} B`;
        if (b < 1024 ** 2) return `${(b / 1024).toFixed(1)} KB`;
        if (b < 1024 ** 3) return `${(b / 1024 ** 2).toFixed(1)} MB`;
        return `${(b / 1024 ** 3).toFixed(2)} GB`;
    }

    function initApiPanel(conn) {
        if (!conn || !isApiConnection(conn)) return;
        _activeConn = conn;

        const meta = conn.metadata || {};
        const urlInput = document.getElementById('api-url');
        if (urlInput) {
            urlInput.value = meta.base_url || meta.endpoint || '';
        }

        const authType = document.getElementById('api-auth-type');
        if (authType && meta.auth_type) {
            authType.value = meta.auth_type;
        }

        const methodSelect = document.getElementById('api-method');
        if (methodSelect && String(conn.source_type || '').toLowerCase() === 'graphql_api') {
            methodSelect.value = 'POST';
            const body = document.getElementById('api-body');
            if (body && !body.value.trim()) {
                body.value = 'query { __typename }';
            }
        }

        setApiTab('params');
        setApiResTab('body');
    }

    async function sendApiRequest() {
        if (!_activeConn) return;

        const method = document.getElementById('api-method')?.value || 'GET';
        const url = document.getElementById('api-url')?.value || '';
        const body = document.getElementById('api-body')?.value || '';
        const authType = document.getElementById('api-auth-type')?.value || 'None';
        const authDetails = document.getElementById('api-auth-details')?.value || '';

        const statusEl = document.getElementById('api-res-status');
        const timeEl = document.getElementById('api-res-time');
        const sizeEl = document.getElementById('api-res-size');
        const bodyEl = document.getElementById('api-response-body');
        const headersEl = document.getElementById('api-response-headers');

        if (statusEl) statusEl.textContent = '…';
        if (bodyEl) bodyEl.textContent = 'Loading…';

        const payload = {
            method,
            url,
            params: parseKvTable('api-params-body'),
            headers: parseKvTable('api-headers-body'),
            body,
            auth_type: authType,
            auth_details: authDetails,
        };

        try {
            const res = await fetch(`/api/proxy/${encodeURIComponent(_activeConn.id)}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await res.json();
            if (!res.ok) {
                throw new Error(data.error || `HTTP ${res.status}`);
            }

            if (statusEl) statusEl.textContent = String(data.status);
            if (timeEl) timeEl.textContent = `${data.time_ms} ms`;
            if (sizeEl) sizeEl.textContent = formatBytes(data.size_bytes);

            let displayBody = data.body_text || '';
            try {
                const parsed = JSON.parse(displayBody);
                displayBody = JSON.stringify(parsed, null, 2);
            } catch { /* keep raw */ }

            if (bodyEl) bodyEl.textContent = displayBody;
            if (headersEl) {
                headersEl.textContent = Object.entries(data.headers || {})
                    .map(([k, v]) => `${k}: ${v}`)
                    .join('\n');
            }
        } catch (e) {
            if (statusEl) statusEl.textContent = 'Error';
            if (bodyEl) bodyEl.textContent = e.message || String(e);
        }
    }

    function bindApiUi() {
        document.querySelectorAll('.api-tab').forEach((btn) => {
            btn.addEventListener('click', () => setApiTab(btn.dataset.apiTab));
        });
        document.querySelectorAll('.api-res-tab').forEach((btn) => {
            btn.addEventListener('click', () => setApiResTab(btn.dataset.apiResTab));
        });
        const sendBtn = document.getElementById('api-send-btn');
        if (sendBtn) sendBtn.addEventListener('click', sendApiRequest);
    }

    window.initApiPanel = initApiPanel;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bindApiUi);
    } else {
        bindApiUi();
    }
})();
