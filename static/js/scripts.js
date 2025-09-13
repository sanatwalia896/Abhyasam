let selectedPageId = "";
let selectedModel = "llama3-8b-8192";

function showTab(tabId) {
    document.querySelectorAll('.tab-content').forEach(tab => tab.classList.remove('active'));
    document.getElementById(tabId).classList.add('active');
}

async function loadNotionPages() {
    try {
        const response = await fetch('/api/notion-pages');
        const pages = await response.json();
        const pageList = document.getElementById('page-list');
        pageList.innerHTML = pages.map(page => 
            `<h3>${page.title}</h3><p>${page.content.slice(0, 100)}...</p>`
        ).join('');
        // Populate settings dropdown
        const select = document.getElementById('page-select');
        select.innerHTML = '<option value="">All Pages</option>' + 
            pages.map(page => `<option value="${page.id}">${page.title}</option>`).join('');
    } catch (error) {
        document.getElementById('page-list').innerText = `Error: ${error.message}`;
    }
}

async function refreshPages() {
    try {
        const response = await fetch(`/api/refresh-notion${selectedPageId ? `?specific_page_id=${selectedPageId}` : ''}`, { method: 'POST' });
        const data = await response.json();
        document.getElementById('page-list').innerHTML = `<p>Updated ${data.pages_updated} pages!</p>`;
    } catch (error) {
        document.getElementById('page-list').innerText = `Error: ${error.message}`;
    }
}

async function sendQuestion() {
    const input = document.getElementById('chat-input');
    const question = input.value.trim();
    if (!question) return;
    
    const history = document.getElementById('chat-history');
    history.innerHTML += `<p><strong>You:</strong> ${question}</p>`;
    
    try {
        const response = await fetch(`/api/chat?question=${encodeURIComponent(question)}&model_name=${selectedModel}`);
        const data = await response.json();
        history.innerHTML += `<p><strong>AI:</strong> ${data.answer}</p>`;
        history.scrollTop = history.scrollHeight;
    } catch (error) {
        history.innerHTML += `<p><strong>Error:</strong> ${error.message}</p>`;
    }
    input.value = '';
}

function saveSettings() {
    selectedPageId = document.getElementById('page-select').value;
    selectedModel = document.getElementById('model-select').value;
    alert(`Settings saved: Page=${selectedPageId || 'All'}, Model=${selectedModel}`);
}

async function generateQuiz() {
    if (!selectedPageId) {
        alert("Please select a page in Settings to generate a quiz.");
        return;
    }
    try {
        const response = await fetch(`/api/generate-quiz?page_id=${selectedPageId}`, { method: 'POST' });
        const data = await response.json();
        if (data.status === "success") {
            window.location.href = data.quiz_url; // Redirect to quiz
        } else {
            alert(`Error: ${data.message}`);
        }
    } catch (error) {
        alert(`Error: ${error.message}`);
    }
}

window.onload = () => loadNotionPages(); // Load pages on start