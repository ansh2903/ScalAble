document.addEventListener('DOMContentLoaded', function () {
    const formFieldsContainer = document.getElementById('form-fields-container');
    const dbType = document.getElementById('db_type').value;

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
        other:      Object.keys(existingData).filter(k => !['id', 'created_at', 'db_type'].includes(k))
    };

    function createField(name, value = '') {
        const label = document.createElement('label');
        label.textContent = name.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        label.setAttribute('for', name);

        const input = document.createElement('input');
        input.type = name.toLowerCase().includes('password') ? 'password' : 'text';
        input.name = name;
        input.id = name;
        input.required = true;
        input.classList.add('form-input');
        input.value = value;

        const wrapper = document.createElement('div');
        wrapper.classList.add('form-group');
        wrapper.appendChild(label);
        wrapper.appendChild(input);
        return wrapper;
    }

    formFieldsContainer.innerHTML = '';
    const fields = dbFields[dbType] || dbFields['other'];
    fields.forEach(field => {
        formFieldsContainer.appendChild(createField(field, existingData[field] || ''));
    });
});
