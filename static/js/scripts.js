async function loadQuiz() {
    const response = await fetch('/api/test');
    const data = await response.json();
    document.getElementById('content').innerText = data.message;
}

function askQuestion() {
    document.getElementById('content').innerText = "Question-answering mode coming soon!";
}
async function refreshPages() {
    const response = await fetch('/api/refresh-notion', { method: 'POST' });
    const data = await response.json();
    document.getElementById('content').innerHTML = `<p>Updated ${data.pages_updated} pages!</p>`;
}