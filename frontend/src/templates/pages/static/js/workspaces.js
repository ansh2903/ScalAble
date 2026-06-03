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
}

function openWorkspace(id) {
    window.location.href = `/chat?workspace_id=${encodeURIComponent(id)}`;
}

async function createWorkspace() {
    const name = window.prompt('Workspace name:', 'New Workspace');
    if (!name || !name.trim()) return;
    const description = window.prompt('Description (optional):', '') || '';

    const res = await fetch('/api/workspaces', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim(), description: description.trim() }),
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        alert(err.error || 'Failed to create workspace');
        return;
    }
    const data = await res.json();
    openWorkspace(data.workspace.id);
}

async function editWorkspace(id, currentName, currentDesc) {
    const name = window.prompt('Workspace name:', currentName);
    if (!name || !name.trim()) return;
    const description = window.prompt('Description:', currentDesc || '') ?? '';

    const res = await fetch(`/api/workspaces/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim(), description: description.trim() }),
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        alert(err.error || 'Failed to update workspace');
        return;
    }
    window.location.reload();
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

document.addEventListener('DOMContentLoaded', hydrateWorkspaceTimestamps);
