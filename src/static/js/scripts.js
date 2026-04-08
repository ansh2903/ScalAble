// ------------------------------------------------------------

// Script for user text, file input handling and dynamic content updates
document.getElementById('hiddenFileInput').addEventListener('change', function(e) {
    const fileInfo = document.getElementById('fileInfo');
    const fileName = document.getElementById('fileName');

    if (this.files && this.files[0]) {
        fileName.textContent = this.files[0].name;
        fileInfo.classList.remove('hidden');
    }
});

function clearFile() {
    document.getElementById('hiddenFileInput').value = '';
    document.getElementById('fileInfo').classList.add('hidden');
}

// 1. Grab elements first
const messageInput = document.getElementById('messageInput');
const sendMessageBtn = document.getElementById('sendMessageBtn');
const chatContainer = document.getElementById('chat-messages-container');

// 2. The Keyboard & Auto-expand Logic
messageInput.addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = (Math.min(this.scrollHeight, 150)) + 'px';
});

messageInput.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (this.value.trim() !== "") {
            sendMessageBtn.click();
        }
    }
});

// 3. The Send Handler
sendMessageBtn.addEventListener('click', async () => {
    const message = messageInput.value.trim();
    const dbId = document.getElementById('selected_db_id').value;

    if (!message || !dbId) return;

    appendMessage('user', message);
    messageInput.value = '';
    
    const assistantMsgId = 'msg-' + Date.now();
    appendMessage('assistant', '', assistantMsgId); // Start empty
    const targetText = document.getElementById(`text-${assistantMsgId}`);

    const formData = new FormData();
    formData.append('message', message);
    formData.append('selected_db_id', dbId);

    try {
        const response = await fetch('/chat/ask', { method: 'POST', body: formData });
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        
        let fullContent = "";

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            
            const chunk = decoder.decode(value);
            const lines = chunk.split('\n');

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const data = JSON.parse(line.slice(6));
                    
                    if (data.type === 'token') {
                        fullContent += data.content;
                        // 500 IQ: Parse XML on the fly for better UI
                        targetText.innerHTML = formatAIResponse(fullContent);
                        chatContainer.scrollTop = chatContainer.scrollHeight;
                    }
                    
                    if (data.type === 'stats') {
                        console.log("Inference Stats:", data);
                    }
                }
            }
        }
    } catch (error) {
        targetText.innerText = "Kernel Panic: Connection Lost.";
    }
});

function formatAIResponse(raw) {
    let html = raw;
    
    // Style the SQL Query block
    html = html.replace(/<query>([\s\S]*?)<\/query>/g, (match, code) => {
        return `
            <div class="my-2 bg-slate-900 rounded-lg p-3 font-mono text-[10px] text-primary border border-slate-700">
                <div class="flex justify-between mb-1 opacity-50 text-[8px] uppercase font-black"><span>SQL Query</span><span class="material-symbols-outlined text-[10px]">terminal</span></div>
                ${code.trim()}
            </div>`;
    });

    // Style the Comment block
    html = html.replace(/<comment>([\s\S]*?)<\/comment>/g, (match, comment) => {
        return `<div class="text-slate-600 italic leading-relaxed">${comment.trim()}</div>`;
    });

    // Handle partial tags during streaming
    return html.replace(/<[^>]*>?/g, ''); 
}

// 4. Enhanced Append Function
function appendMessage(role, text, id = null) {
    const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    let messageHtml = '';

    if (role === 'user') {
        messageHtml = `
            <div class="flex gap-2 flex-row-reverse animate-in fade-in slide-in-from-right-2 duration-300">
                <div class="w-7 h-7 rounded-full border border-primary/30 p-0.5 flex-shrink-0 overflow-hidden">
                    <img alt="User" class="w-full h-full rounded-full object-cover" src="https://lh3.googleusercontent.com/aida-public/AB6AXuC-f8TTx8bBFUGqf42OM1R8Whfp3LjOOu2WEloffe2jYBHPfQcKaeyjHmuVd63Bs2LDTjCA3I93KOac7gbt8YG-FEPRoRvMcdVC2iqfKG70hmYfY6H7Kf3IcG8yRYB-IeHgKeQyuvchqYFdQax1K2lZcRX77iUk5ZogtDQOGUXL3kQCYu4uCEfzxirkqHf0JZXlTK3eN5gwMwKj800imCj98mrQCiklCItJ985ijbYgJhjBnjHzQ84J-xW__OOEZNQDsZ_97qLA5Lcg" />
                </div>
                <div class="bg-primary text-white px-2.5 py-2 rounded-xl rounded-tr-none shadow-tactile max-w-[92%]">
                    <p class="text-xs leading-snug font-bold">${text}</p>
                    <span class="text-[8px] text-primary-soft/80 mt-1 block font-black uppercase tracking-wider">You • ${time}</span>
                </div>
            </div>`;
    } else {
        messageHtml = `
            <div class="flex gap-2 animate-in fade-in slide-in-from-left-2 duration-300" id="${id}">
                <div class="w-7 h-7 rounded-xl bg-primary organic-border flex-shrink-0 flex items-center justify-center shadow-tactile">
                    <span class="material-symbols-outlined text-white text-xs" style="font-variation-settings: 'FILL' 1;">auto_awesome</span>
                </div>
                <div class="bg-white px-2.5 py-2 rounded-xl rounded-tl-none border border-slate-100 shadow-data-card max-w-[92%]">
                    <p id="text-${id}" class="text-xs leading-snug text-slate-700 font-medium">${text}</p>
                    <span class="text-[8px] text-slate-400 mt-1 block font-black uppercase tracking-wider">Assistant • ${time}</span>
                </div>
            </div>`;
    }

    chatContainer.insertAdjacentHTML('beforeend', messageHtml);
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

// ----------------------------------------------------------------------------

// Script for system metrics SSE
const eventSource = new EventSource("/system-metrics");

eventSource.onmessage = function(event) {
    const stats = JSON.parse(event.data);
    document.getElementById("cpu-stat").innerText = `CPU: ${stats.cpu}`;
    document.getElementById("ram-stat").innerText = `RAM: ${stats.ram}`;
};

eventSource.onerror = function() {
    console.error("Metrics stream error");
};
// ----------------------------------------------------------------------------

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

