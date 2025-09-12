async function loadQuiz() {
    const response = await fetch('/api/test');
    const data = await response.json();
    document.getElementById('content').innerText = data.message;
}

function askQuestion() {
    document.getElementById('content').innerText = "Question-answering mode coming soon!";
}