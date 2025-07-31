async function fetchDatabases() {
    const uri = document.getElementById("uri").value;
    const response = await fetch("/list_databases", {
        method: "POST",
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ uri })
    });

    const data = await response.json();
    populateSelect("db-select", data.databases);

    document.getElementById("db-section").style.display = "block";
    document.getElementById("collection-section").style.display = "none";
    document.getElementById("query-section").style.display = "none";
}

async function fetchCollections() {
    const uri = document.getElementById("uri").value;
    const db = document.getElementById("db-select").value;
    const response = await fetch("/list_collections", {
        method: "POST",
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ uri, database: db })
    });

    const data = await response.json();
    populateSelect("collection-select", data.collections);

    document.getElementById("collection-section").style.display = "block";
    document.getElementById("query-section").style.display = "block";
}

// Utility to populate a dropdown
function populateSelect(selectId, items) {
    const select = document.getElementById(selectId);
    select.innerHTML = "";
    items.forEach(item => {
        const option = document.createElement("option");
        option.value = item;
        option.text = item;
        select.appendChild(option);
    });
}

document.addEventListener("DOMContentLoaded", () => {
    // Sidebar toggle
    const sidebar = document.querySelector('.sidebar');
    const toggleBtn = document.getElementById('sidebar-toggle');
    const closeBtn = document.getElementById("sidebar-close");

    if (closeBtn && sidebar) {
        closeBtn.addEventListener('click', () => {
            sidebar.classList.remove('open');
            toggleBtn?.setAttribute('aria-expanded', 'false');
        });
    }

    const toggleSidebar = () => {
        const isOpen = sidebar.classList.toggle('open');
        toggleBtn?.setAttribute('aria-expanded', isOpen);
    };

    toggleBtn?.addEventListener('click', toggleSidebar);
    closeBtn?.addEventListener('click', () => {
        sidebar.classList.remove('open');
        toggleBtn?.setAttribute('aria-expanded', 'false');
    });

    window.addEventListener('resize', () => {
        if (window.innerWidth > 1024) {
            sidebar?.classList.remove('open');
            toggleBtn?.setAttribute('aria-expanded', 'false');
        }
    });

    // Optional preload: MongoDB example (for connected clients)
    const dbSelect = document.getElementById("db-select");
    const colSelect = document.getElementById("collection-select");

    if (dbSelect && colSelect) {
        fetch("/api/databases")
            .then(res => res.json())
            .then(dbs => populateSelect("db-select", dbs));

        dbSelect.addEventListener("change", () => {
            fetch(`/api/collections/${dbSelect.value}`)
                .then(res => res.json())
                .then(cols => populateSelect("collection-select", cols));
        });
    }
});

document.addEventListener('DOMContentLoaded', function() {
    const dbSelect = document.getElementById('selected_db');
    dbSelect.addEventListener('change', function() {
        const selectedOption = dbSelect.options[dbSelect.selectedIndex];
        if (selectedOption.value === 'configure_db') {
            window.location.href = selectedOption.getAttribute('data-link');
        }
    });
});

