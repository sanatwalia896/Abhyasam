document.addEventListener('DOMContentLoaded', () => {
  const pageSelect = document.getElementById('page-select');
  const refreshBtn = document.getElementById('refresh-btn');
  const questionInput = document.getElementById('question-input');
  const sendBtn = document.getElementById('send-btn');
  const chatArea = document.getElementById('chat-area');
  const quizLink = document.getElementById('quiz-link');
  const loading = document.getElementById('loading');
  const quizGenerationModal = document.createElement('div');
  quizGenerationModal.id = 'quiz-generation-modal';
  quizGenerationModal.className = 'modal hidden';
  quizGenerationModal.innerHTML = `
    <div class="modal-content">
      <div class="modal-header">
        <h3>Generating Quiz</h3>
      </div>
      <div class="modal-body">
        <div class="loader">
          <i class="fas fa-brain brain-loader"></i>
          <p id="generation-message">Generating questions, please wait...</p>
        </div>
      </div>
    </div>
  `;
  document.body.appendChild(quizGenerationModal);
  const generationMessage = quizGenerationModal.querySelector('#generation-message');

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

  // Get page_title from URL
  const urlParams = new URLSearchParams(window.location.search);
  const pageTitle = urlParams.get('page_title');

  async function loadPages() {
    loading.classList.remove('hidden');
    try {
      const response = await fetch('/api/notion-pages');
      const data = await response.json();
      if (data.status === 'success') {
        pageSelect.innerHTML = '<option value="">Select a Notion page</option>';
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
    updateQuizLink();
  }

  async function refreshPages() {
    loading.classList.remove('hidden');
    try {
      const response = await fetch('/api/refresh-notion', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force: true })
      });
      const result = await response.json();
      if (result.status === 'success') {
        await loadPages();
        alert('Notion pages refreshed successfully!');
      } else {
        alert('Error refreshing Notion pages');
      }
    } catch (error) {
      console.error('Error refreshing pages:', error);
      alert('Failed to refresh Notion pages.');
    } finally {
      loading.classList.add('hidden');
    }
  }

  function updateQuizLink() {
    const selectedTitle = pageSelect.value || pageTitle;
    if (selectedTitle) {
      quizLink.href = `/quiz?page_title=${encodeURIComponent(selectedTitle)}`;
    } else {
      quizLink.href = '/quiz';
    }
  }

  async function generateQuiz() {
    quizGenerationModal.classList.remove('hidden');
    generationMessage.textContent = `Generating questions for ${pageSelect.value}, please wait...`;
    try {
      const response = await fetch('/api/generate-quiz', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          topic_query: pageSelect.options[pageSelect.selectedIndex].text,
          num_batches: 3,
          questions_per_batch: 10,
          page_title: pageSelect.value
        })
      });
      const result = await response.json();
      if (result.status === 'success') {
        generationMessage.textContent = `Generated ${result.questions_count} questions in ${result.generation_time}s!`;
        await new Promise(resolve => setTimeout(resolve, 1000)); // Brief pause to show success
        return result;
      } else {
        throw new Error(result.detail || 'Failed to generate quiz');
      }
    } catch (error) {
      console.error('Error generating quiz:', error);
      alert(`Failed to generate quiz: ${error.message}`);
      throw error;
    } finally {
      quizGenerationModal.classList.add('hidden');
    }
  }

  async function sendQuestion() {
    const question = questionInput.value.trim();
    if (!question) {
      alert('Please enter a question');
      return;
    }
    if (!pageSelect.value) {
      alert('Please select a Notion page');
      return;
    }

    const userMessageDiv = document.createElement('div');
    userMessageDiv.className = 'message user';
    userMessageDiv.textContent = question;
    chatArea.appendChild(userMessageDiv);
    chatArea.scrollTop = chatArea.scrollHeight;
    loading.classList.remove('hidden');

    if (question.toLowerCase() === 'quiz') {
      try {
        const result = await generateQuiz();
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message ai';
        messageDiv.innerHTML = marked.parse(`Quiz generated for **${pageSelect.value}**! [Take the quiz](/quiz?page_title=${encodeURIComponent(pageSelect.value)})`);
        chatArea.appendChild(messageDiv);
        chatArea.scrollTop = chatArea.scrollHeight;
      } catch (error) {
        alert('Failed to generate quiz.');
      }
    } else {
      try {
        const response = await fetch('/api/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question, session_id: 'user1', page_title: pageSelect.value })
        });
        const result = await response.json();
        if (result.status === 'success') {
          const messageDiv = document.createElement('div');
          messageDiv.className = 'message ai';
          // Parse the response as Markdown using marked.js
          try {
            messageDiv.innerHTML = marked.parse(result.answer);
          } catch (e) {
            console.error('Markdown parsing error:', e);
            // Fallback: display plain text if Markdown parsing fails
            messageDiv.textContent = result.answer;
          }
          chatArea.appendChild(messageDiv);
          chatArea.scrollTop = chatArea.scrollHeight;
        } else {
          alert('Error getting response: ' + (result.detail || 'Unknown error'));
        }
      } catch (error) {
        console.error('Error sending question:', error);
        alert('Failed to get response.');
      }
    }
    questionInput.value = '';
    loading.classList.add('hidden');
  }

  pageSelect.addEventListener('change', updateQuizLink);
  refreshBtn.addEventListener('click', refreshPages);
  sendBtn.addEventListener('click', sendQuestion);
  questionInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendQuestion();
  });

  // Load pages on page load
  loadPages();
});