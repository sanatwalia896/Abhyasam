document.addEventListener('DOMContentLoaded', () => {
  const API_BASE = 'https://abhyasam.onrender.com';
  const pageSelect = document.getElementById('page-select');
  const refreshBtn = document.getElementById('refresh-btn');
  const quizBtn = document.getElementById('quiz-btn');
  const chatBtn = document.getElementById('chat-btn');
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
  
  async function loadPages() {
    loading.classList.remove('hidden');
    try {
      const response = await fetch(`${API_BASE}/api/notion-pages`);
      const data = await response.json();
      if (data.status === 'success') {
        pageSelect.innerHTML = '<option value="">Select a Notion page</option>';
        data.pages.forEach(page => {
          const option = document.createElement('option');
          option.value = page.title;
          option.textContent = page.title;
          pageSelect.appendChild(option);
        });
      } else {
        alert('Error loading Notion pages');
      }
    } catch (error) {
      console.error('Failed to load pages:', error);
      alert('Failed to load Notion pages. Please try refreshing.');
    } finally {
      loading.classList.add('hidden');
    }
    toggleButtons();
  }

  async function refreshPages() {
    loading.classList.remove('hidden');
    try {
      const response = await fetch(`${API_BASE}/api/refresh-notion`, {
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

  function toggleButtons() {
    const isSelected = pageSelect.value !== '';
    quizBtn.disabled = !isSelected;
    chatBtn.disabled = !isSelected;
  }

  async function startQuiz() {
    if (!pageSelect.value) return;
    loading.classList.remove('hidden');
    try {
      const response = await fetch(`${API_BASE}/api/generate-quiz`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ page_title: pageSelect.value })
      });
      const result = await response.json();
      if (result.status === 'success') {
        window.location.href = `/quiz.html?page_title=${encodeURIComponent(pageSelect.value)}`;
      } else {
        alert('Error generating quiz');
      }
    } catch (error) {
      console.error('Error generating quiz:', error);
      alert('Failed to generate quiz.');
    } finally {
      loading.classList.add('hidden');
    }
  }

  function startChat() {
    if (!pageSelect.value) return;
    window.location.href = `/chat.html?page_title=${encodeURIComponent(pageSelect.value)}`;
  }

  pageSelect.addEventListener('change', toggleButtons);
  refreshBtn.addEventListener('click', refreshPages);
  quizBtn.addEventListener('click', startQuiz);
  chatBtn.addEventListener('click', startChat);

  loadPages();
});
