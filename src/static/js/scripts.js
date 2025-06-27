async function fetchDatabases() {
    const uri = document.getElementById("uri").value;
    const response = await fetch("/list_databases", {
        method: "POST",
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ uri })
    });
    const data = await response.json();
    const dbSelect = document.getElementById("db-select");

    dbSelect.innerHTML = "";
    data.databases.forEach(db => {
        const option = document.createElement("option");
        option.value = db;
        option.text = db;
        dbSelect.appendChild(option);
    });

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
    const collectionSelect = document.getElementById("collection-select");

    collectionSelect.innerHTML = "";
    data.collections.forEach(coll => {
        const option = document.createElement("option");
        option.value = coll;
        option.text = coll;
        collectionSelect.appendChild(option);
    });

    document.getElementById("collection-section").style.display = "block";
    document.getElementById("query-section").style.display = "block";
}

document.addEventListener("DOMContentLoaded", function () {
    // Sidebar toggle logic
    const sidebar = document.querySelector('.sidebar');
    const toggleBtn = document.getElementById('sidebar-toggle');

    if (toggleBtn && sidebar) {
        toggleBtn.addEventListener('click', function () {
            const isOpen = sidebar.classList.toggle('open');
            toggleBtn.setAttribute('aria-expanded', isOpen);
        });
    }

    window.addEventListener('resize', function () {
        if (window.innerWidth > 1024 && sidebar) {
            sidebar.classList.remove('open');
            if (toggleBtn) toggleBtn.setAttribute('aria-expanded', 'false');
        }
    });

    // Database and collection select logic
    const dbSelect = document.getElementById("db-select");
    const colSelect = document.getElementById("collection-select");

    if (dbSelect && colSelect) {
        fetch("/api/databases")
            .then(res => res.json())
            .then(dbs => {
                dbSelect.innerHTML = "";
                dbs.forEach(db => {
                    let opt = document.createElement("option");
                    opt.value = db;
                    opt.textContent = db;
                    dbSelect.appendChild(opt);
                });
            });

        dbSelect.addEventListener("change", function () {
            colSelect.innerHTML = '';
            fetch(`/api/collections/${dbSelect.value}`)
                .then(res => res.json())
                .then(cols => {
                    cols.forEach(col => {
                        let opt = document.createElement("option");
                        opt.value = col;
                        opt.textContent = col;
                        colSelect.appendChild(opt);
                    });
                });
        });
    }
});