document.addEventListener('DOMContentLoaded', function() {
    const dbTypeCards = document.querySelectorAll('.db-type-card');
    const dbTypeGrid = document.getElementById('db-type-grid');
    const formFieldsContainer = document.getElementById('form-fields-container');
    const dbTypeInput = document.getElementById('db_type');
    const backBtn = document.getElementById('back-btn');
    const continueBtn = document.getElementById('continue-btn');
    const selectedDbType = document.getElementById('selected-db-type');
    const selectedDbTypeLabel = document.getElementById('selected-db-type-label');

    // Define fields for each db type
    const dbFields = {
        mysql:      ['name', 'host', 'port', 'username', 'password', 'database'],
        postgresql: ['name', 'host', 'port', 'username', 'password', 'database'],
        mongodb:    ['name', 'uri'],
        sqlite:     ['name', 'file_path'],
        mssql:      ['name', 'driver', 'server', 'database'],
        oracle:     ['name', 'host', 'port', 'service_name', 'username', 'password'],
        redshift:   ['name', 'host', 'port', 'username', 'password', 'database'],
        bigquery:   ['name', 'project_id', 'credentials_json'],
        mariadb:    ['name', 'host', 'port', 'username', 'password', 'database'],
        snowflake:  ['name', 'account', 'user', 'password', 'database', 'schema', 'warehouse'],
        clickhouse: ['name', 'host', 'port', 'username', 'password', 'database'],
        other:      ['name', 'host', 'port', 'username', 'password', 'database']
    };

    function createField(name) {
        const label = document.createElement('label');
        label.textContent = name.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        label.setAttribute('for', name);

        const input = document.createElement('input');
        input.type = name.toLowerCase().includes('password') ? 'password' : 'text';
        input.name = name;
        input.id = name;
        input.required = true;
        input.classList.add('form-input');

        const wrapper = document.createElement('div');
        wrapper.appendChild(label);
        wrapper.appendChild(input);
        return wrapper;
    }

    dbTypeCards.forEach(card => {
        card.addEventListener('click', function() {
            const dbType = card.dataset.dbtype;
            dbTypeInput.value = dbType;

            // Show selected db type
            selectedDbTypeLabel.textContent = card.dataset.label;
            selectedDbType.classList.remove('hidden');

            // Hide grid, show form
            dbTypeGrid.classList.add('hidden');
            formFieldsContainer.classList.remove('hidden');
            backBtn.classList.remove('hidden');
            continueBtn.classList.remove('hidden');

            // Clear and populate fields
            formFieldsContainer.innerHTML = '';
            (dbFields[dbType] || dbFields['other']).forEach(field => {
                formFieldsContainer.appendChild(createField(field));
            });
        });
    });

    backBtn.addEventListener('click', function() {
        dbTypeGrid.classList.remove('hidden');
        formFieldsContainer.classList.add('hidden');
        backBtn.classList.add('hidden');
        continueBtn.classList.add('hidden');
        selectedDbType.classList.add('hidden');
        dbTypeInput.value = '';
        formFieldsContainer.innerHTML = '';
    });
});