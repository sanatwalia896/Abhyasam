document.addEventListener('DOMContentLoaded', () => {
  const pageSelect = document.getElementById('page-select');
  const numQuestionsInput = document.getElementById('num-questions');
  const startQuizBtn = document.getElementById('start-quiz-btn');
  const quizContainer = document.getElementById('quiz-container');
  const quizProgress = document.getElementById('quiz-progress');
  const quizMessages = document.getElementById('quiz-messages');
  const answerInput = document.getElementById('answer-input');
  const submitAnswerBtn = document.getElementById('submit-answer-btn');
  const loading = document.getElementById('loading');

  // Initialize particles.js
  particlesJS('particles', {
    particles: {
      number: { value: 50, density: { enable: true, value_area: 800 } },
      color: { value: '#ffffff' },
      shape: { type: 'circle' },
      opacity: { value: 0.3, random: true },
      size: { value: 3, random: true },
      move: { enable: true, speed: 1, direction: 'top', random: true }
    },
    interactivity: { detect_on: 'canvas', events: { onhover: { enable: false } } }
  });

  // Get page_title from URL if present
  const urlParams = new URLSearchParams(window.location.search);
  const pageTitle = urlParams.get('page_title');

  async function loadPages() {
    loading.classList.remove('hidden');
    try {
      const response = await fetch('/api/notion-pages');
      const data = await response.json();
      if (data.status === 'success') {
        pageSelect.innerHTML = '<option value="">Select a Notion page (optional)</option>';
        data.pages.forEach(page => {
          const option = document.createElement('option');
          option.value = page.title;
          option.textContent = page.title;
          if (page.title === pageTitle) option.selected = true;
          pageSelect.appendChild(option);
        });
      } else {
        alert('Error loading Notion pages');
      }
    } catch (error) {
      console.error('Failed to load pages:', error);
      alert('Failed to load Notion pages.');
    } finally {
      loading.classList.add('hidden');
    }
  }

  async function startQuiz() {
    const numQuestions = parseInt(numQuestionsInput.value);
    if (isNaN(numQuestions) || numQuestions < 1) {
      alert('Please enter a valid number of questions (at least 1)');
      return;
    }
    const pageTitle = pageSelect.value;

    loading.classList.remove('hidden');
    try {
      const response = await fetch('/api/start-quiz', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          num_questions: numQuestions,
          session_id: 'user1',
          page_title: pageTitle || null
        })
      });
      const result = await response.json();
      if (result.status === 'success') {
        quizContainer.classList.remove('hidden');
        quizMessages.innerHTML = ''; // Clear previous messages
        addMessage('ai', `Question ${result.question_number}/${result.total_questions}: ${result.question}`);
        quizProgress.textContent = `Question ${result.question_number} of ${result.total_questions}`;
        startQuizBtn.disabled = true; // Disable start button during quiz
      } else {
        alert(result.message || 'Failed to start quiz');
      }
    } catch (error) {
      console.error('Error starting quiz:', error);
      alert('Failed to start quiz.');
    } finally {
      loading.classList.add('hidden');
    }
  }

  async function submitAnswer() {
    const answer = answerInput.value.trim();
    if (!answer) {
      alert('Please enter an answer');
      return;
    }

    addMessage('user', answer);
    loading.classList.remove('hidden');
    try {
      const response = await fetch('/api/submit-quiz-answer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          answer: answer,
          session_id: 'user1'
        })
      });
      const result = await response.json();
      if (result.status === 'success') {
        addMessage('ai', `Feedback: ${result.previous_feedback} (Score: ${result.previous_score}/10)`);
        quizProgress.textContent = `Question ${result.question_number} of ${result.total_questions}`;
        addMessage('ai', `Question ${result.question_number}/${result.total_questions}: ${result.question}`);
      } else if (result.status === 'complete') {
        addMessage('ai', `Feedback: ${result.previous_feedback} (Score: ${result.previous_score}/10)`);
        addMessage('ai', result.message);
        quizContainer.classList.add('hidden');
        startQuizBtn.disabled = false; // Re-enable start button
      } else {
        alert(result.message || 'Failed to submit answer');
      }
    } catch (error) {
      console.error('Error submitting answer:', error);
      alert('Failed to submit answer.');
    } finally {
      answerInput.value = '';
      loading.classList.add('hidden');
      quizMessages.scrollTop = quizMessages.scrollHeight;
    }
  }

  function addMessage(type, content) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${type}`;
    messageDiv.textContent = content;
    quizMessages.appendChild(messageDiv);
    quizMessages.scrollTop = quizMessages.scrollHeight;
  }

  startQuizBtn.addEventListener('click', startQuiz);
  submitAnswerBtn.addEventListener('click', submitAnswer);
  answerInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submitAnswer();
    }
  });

  // Load pages on page load
  loadPages();
});