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
    const dbSelect = document.getElementById("database");
    const colSelect = document.getElementById("collection");

    fetch("/api/databases")
        .then(res => res.json())
        .then(dbs => {
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
});
