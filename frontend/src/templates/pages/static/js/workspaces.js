/**
 * Mission Control — workspace list CRUD (index page).
 */

function formatWorkspaceUpdated(iso) {
    if (!iso) return '—';
    const ts = Date.parse(iso);
    if (Number.isNaN(ts)) return '—';
    const diff = Math.max(0, (Date.now() - ts) / 1000);
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
    if (diff < 604800) return `${Math.round(diff / 86400)}d ago`;
    return new Date(ts).toLocaleDateString();
}

function hydrateWorkspaceTimestamps() {
    document.querySelectorAll('.workspace-updated').forEach((el) => {
        const raw = el.dataset.updated;
        el.textContent = `Updated ${formatWorkspaceUpdated(raw)}`;
    });
    document.querySelectorAll('.workspace-created').forEach((el) => {
        const raw = el.dataset.created;
        el.textContent = `Created ${formatWorkspaceUpdated(raw)}`;
    });
}

function filterWorkspaces(query) {
    const q = (query || '').trim().toLowerCase();
    document.querySelectorAll('.workspace-card').forEach((card) => {
        const name = card.dataset.name || '';
        const desc = card.dataset.description || '';
        const match = !q || name.includes(q) || desc.includes(q);
        card.classList.toggle('hidden', !match);
    });
}

function openWorkspaceModal(detail) {
    window.dispatchEvent(new CustomEvent('workspace-modal:open', { detail: detail || {} }));
}

function openWorkspace(id) {
    window.location.href = `/chat?workspace_id=${encodeURIComponent(id)}`;
}

function createWorkspace() {
    openWorkspaceModal({
        mode: 'create',
        name: 'New Workspace',
        description: '',
    });
}

function editWorkspace(id, currentName, currentDesc) {
    openWorkspaceModal({
        mode: 'edit',
        id,
        name: currentName || '',
        description: currentDesc || '',
    });
}

async function deleteWorkspace(id, name) {
    if (!window.confirm(`Delete workspace "${name}"? This cannot be undone.`)) return;

    const res = await fetch(`/api/workspaces/${encodeURIComponent(id)}`, {
        method: 'DELETE',
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        alert(err.error || 'Failed to delete workspace');
        return;
    }
    window.location.reload();
}

function workspaceModal() {
    return {
        open: false,
        mode: 'create',
        id: '',
        name: '',
        description: '',
        error: '',
        saving: false,

        init() {
            window.addEventListener('workspace-modal:open', (e) => {
                const d = e.detail || {};
                this.mode = d.mode || 'create';
                this.id = d.id || '';
                this.name = d.name ?? '';
                this.description = d.description ?? '';
                this.error = '';
                this.saving = false;
                this.open = true;
                this.$nextTick(() => this.$refs.nameInput?.focus());
            });
        },

        close() {
            this.open = false;
            this.error = '';
        },

        async submit() {
            const name = (this.name || '').trim();
            if (!name) {
                this.error = 'Workspace name is required.';
                return;
            }

            this.saving = true;
            this.error = '';

            try {
                if (this.mode === 'edit') {
                    const res = await fetch(`/api/workspaces/${encodeURIComponent(this.id)}`, {
                        method: 'PATCH',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            name,
                            description: (this.description || '').trim(),
                        }),
                    });
                    if (!res.ok) {
                        const err = await res.json().catch(() => ({}));
                        this.error = err.error || 'Failed to update workspace';
                        return;
                    }
                    window.location.reload();
                    return;
                }

                const res = await fetch('/api/workspaces', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name,
                        description: (this.description || '').trim(),
                    }),
                });
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    this.error = err.error || 'Failed to create workspace';
                    return;
                }
                const data = await res.json();
                openWorkspace(data.workspace.id);
            } catch (_err) {
                this.error = 'Something went wrong. Please try again.';
            } finally {
                this.saving = false;
            }
        },
    };
}

document.addEventListener('DOMContentLoaded', hydrateWorkspaceTimestamps);
