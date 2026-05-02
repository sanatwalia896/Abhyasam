const API_BASE = 'https://abhyasam.onrender.com';
// const API_BASE="http://localhost:8000"
let flashcards = [];
let currentIndex = 0;

document.addEventListener('DOMContentLoaded', () => {
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

  loadFlashcards();
});

async function loadFlashcards() {
  const loading = document.getElementById('loading');
  const viewer = document.getElementById('flashcard-viewer');
  
  loading.classList.remove('hidden');
  viewer.classList.add('hidden');

  try {
    const response = await fetch(`${API_BASE}/api/flashcards`);
    const data = await response.json();
    
    if (data.status === 'success' && data.flashcards.length > 0) {
      flashcards = data.flashcards;
      currentIndex = 0;
      
      const urlParams = new URLSearchParams(window.location.search);
      const pageTitle = urlParams.get('page_title');
      document.getElementById('page-title-display').textContent = pageTitle ? `Topic: ${pageTitle}` : 'All topics';
      
      updateFlashcardDisplay();
      viewer.classList.remove('hidden');
    } else {
      document.getElementById('page-title-display').textContent = 'No flashcards found.';
    }
  } catch (error) {
    console.error('Error fetching flashcards:', error);
    document.getElementById('page-title-display').textContent = 'Failed to load flashcards.';
  } finally {
    loading.classList.add('hidden');
  }
}

function updateFlashcardDisplay() {
  if (flashcards.length === 0) return;
  
  const currentCard = flashcards[currentIndex];
  document.getElementById('flashcard-front-content').innerHTML = currentCard.front.replace(/\n/g, '<br>');
  document.getElementById('flashcard-back-content').innerHTML = currentCard.back.replace(/\n/g, '<br>');
  document.getElementById('flashcard-counter').textContent = `${currentIndex + 1} / ${flashcards.length}`;
  
  const cardElement = document.getElementById('active-flashcard');
  cardElement.classList.remove('is-flipped');
  
  document.getElementById('prev-btn').disabled = currentIndex === 0;
  document.getElementById('next-btn').disabled = currentIndex === flashcards.length - 1;
}

window.toggleFlip = function() {
  const card = document.getElementById('active-flashcard');
  card.classList.toggle('is-flipped');
};

window.prevCard = function() {
  if (currentIndex > 0) {
    currentIndex--;
    updateFlashcardDisplay();
  }
};

window.nextCard = function() {
  if (currentIndex < flashcards.length - 1) {
    currentIndex++;
    updateFlashcardDisplay();
  }
};
