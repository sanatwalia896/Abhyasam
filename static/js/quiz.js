// static/js/quiz.js
class QuizApp {
  constructor() {
    this.questions = [];
    this.currentQuestionIndex = 0;
    this.userAnswers = {};
    this.bookmarkedQuestions = new Set();
    this.score = 0;
    this.timer = null;
    this.timeRemaining = 90 * 60;
    this.startTime = null;
    this.endTime = null;

    this.elements = {
      screens: {
        start: document.getElementById('start-screen'),
        quiz: document.getElementById('quiz-screen'),
        results: document.getElementById('results-screen'),
        review: document.getElementById('review-screen')
      },
      startBtn: document.getElementById('start-btn'),
      timerDisplay: document.getElementById('timer-display'),
      questionCounter: document.getElementById('question-counter'),
      progressFill: document.getElementById('progress-fill'),
      progressText: document.getElementById('progress-text'),
      questionNumber: document.getElementById('question-number'),
      questionText: document.getElementById('question-text'),
      optionsContainer: document.getElementById('options-container'),
      prevBtn: document.getElementById('prev-btn'),
      nextBtn: document.getElementById('next-btn'),
      submitBtn: document.getElementById('submit-btn'),
      bookmarkBtn: document.getElementById('bookmark-btn'),
      fullscreenBtn: document.getElementById('fullscreen-btn'),
      showNavBtn: document.getElementById('show-nav-btn'),
      questionNav: document.getElementById('question-nav'),
      closeNavBtn: document.getElementById('close-nav'),
      questionGrid: document.getElementById('question-grid'),
      submitModal: document.getElementById('submit-modal'),
      cancelSubmit: document.getElementById('cancel-submit'),
      confirmSubmit: document.getElementById('confirm-submit'),
      loadingOverlay: document.getElementById('loading-overlay'),
      reviewBtn: document.getElementById('review-btn'),
      restartBtn: document.getElementById('restart-btn'),
      shareBtn: document.getElementById('share-btn'),
      closeReview: document.getElementById('close-review'),
      reviewContent: document.getElementById('review-content')
    };

    this.init();
  }

  async init() {
    try {
      this.setupEventListeners();
      this.createParticles();
      await this.loadQuestions();
      this.hideLoading();
    } catch (error) {
      console.error('Failed to initialize quiz:', error);
      this.hideLoading();
    }
  }

  async loadQuestions() {
    try {
      const response = await fetch('/static/questions.json');
      this.questions = await response.json();
      this.generateQuestionGrid();
    } catch (error) {
      console.error('Failed to load questions:', error);
      this.questions = [
        {
          question: "Sample question",
          options: ["Option A", "Option B", "Option C", "Option D"],
          answer: 0
        }
      ];
      this.generateQuestionGrid();
    }
  }

  setupEventListeners() {
    this.elements.startBtn.addEventListener('click', () => this.startQuiz());
    this.elements.prevBtn.addEventListener('click', () => this.previousQuestion());
    this.elements.nextBtn.addEventListener('click', () => this.nextQuestion());
    this.elements.submitBtn.addEventListener('click', () => this.showSubmitModal());
    this.elements.bookmarkBtn.addEventListener('click', () => this.toggleBookmark());
    this.elements.fullscreenBtn.addEventListener('click', () => this.toggleFullscreen());
    this.elements.showNavBtn.addEventListener('click', () => this.showQuestionNavigator());
    this.elements.closeNavBtn.addEventListener('click', () => this.hideQuestionNavigator());
    this.elements.cancelSubmit.addEventListener('click', () => this.hideSubmitModal());
    this.elements.confirmSubmit.addEventListener('click', () => this.submitQuiz());
    this.elements.reviewBtn.addEventListener('click', () => this.showReview());
    this.elements.restartBtn.addEventListener('click', () => this.restartQuiz());
    this.elements.shareBtn.addEventListener('click', () => this.shareResults());
    this.elements.closeReview.addEventListener('click', () => this.hideReview());
    document.addEventListener('keydown', (e) => this.handleKeyPress(e));
    window.addEventListener('beforeunload', (e) => {
      if (this.isQuizActive()) {
        e.preventDefault();
        e.returnValue = 'Are you sure you want to leave? Your progress will be lost.';
      }
    });
  }

  createParticles() {
    const particlesContainer = document.getElementById('particles');
    for (let i = 0; i < 50; i++) {
      const particle = document.createElement('div');
      particle.className = 'particle';
      const size = Math.random() * 6 + 2;
      particle.style.width = `${size}px`;
      particle.style.height = `${size}px`;
      particle.style.left = `${Math.random() * 100}%`;
      particle.style.animationDelay = `${Math.random() * 20}s`;
      particle.style.animationDuration = `${Math.random() * 10 + 10}s`;
      particlesContainer.appendChild(particle);
    }
  }

  showScreen(screenName) {
    Object.values(this.elements.screens).forEach(screen => {
      screen.classList.remove('active');
    });
    this.elements.screens[screenName].classList.add('active');
  }

  hideLoading() {
    this.elements.loadingOverlay.classList.add('hidden');
  }

  startQuiz() {
    this.showScreen('quiz');
    this.startTime = new Date();
    this.startTimer();
    this.showQuestion();
    this.updateProgress();
    this.updateNavigationButtons();
  }

  startTimer() {
    const timerDisplay = this.elements.timerDisplay;
    this.timer = setInterval(() => {
      this.timeRemaining--;
      const minutes = Math.floor(this.timeRemaining / 60);
      const seconds = this.timeRemaining % 60;
      timerDisplay.textContent = `${minutes}:${seconds.toString().padStart(2, '0')}`;
      if (this.timeRemaining <= 300 && this.timeRemaining > 0) {
        this.elements.timerDisplay.parentElement.classList.add('warning');
      }
      if (this.timeRemaining <= 0) {
        this.autoSubmitQuiz();
      }
    }, 1000);
  }

  stopTimer() {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  showQuestion() {
    const question = this.questions[this.currentQuestionIndex];
    if (!question) return;
    this.elements.questionNumber.textContent = `Question ${this.currentQuestionIndex + 1} of ${this.questions.length}`;
    this.elements.questionText.textContent = question.question;
    this.elements.questionCounter.textContent = `Question ${this.currentQuestionIndex + 1} of ${this.questions.length}`;
    this.elements.optionsContainer.innerHTML = '';
    question.options.forEach((option, index) => {
      const optionDiv = document.createElement('div');
      optionDiv.className = `option ${this.userAnswers[this.currentQuestionIndex] === index ? 'selected' : ''}`;
      optionDiv.innerHTML = `${String.fromCharCode(65 + index)}. ${option}`;
      optionDiv.addEventListener('click', () => {
        this.userAnswers[this.currentQuestionIndex] = index;
        this.showQuestion();
        this.updateProgress();
        this.updateNavigationButtons();
        this.updateQuestionNavigator();
      });
      this.elements.optionsContainer.appendChild(optionDiv);
    });
    this.updateBookmarkButton();
  }

  previousQuestion() {
    if (this.currentQuestionIndex > 0) {
      this.currentQuestionIndex--;
      this.showQuestion();
      this.updateNavigationButtons();
      this.updateQuestionNavigator();
    }
  }

  nextQuestion() {
    if (this.currentQuestionIndex < this.questions.length - 1) {
      this.currentQuestionIndex++;
      this.showQuestion();
      this.updateNavigationButtons();
      this.updateQuestionNavigator();
    }
  }

  toggleBookmark() {
    if (this.bookmarkedQuestions.has(this.currentQuestionIndex)) {
      this.bookmarkedQuestions.delete(this.currentQuestionIndex);
      this.elements.bookmarkBtn.classList.remove('active');
    } else {
      this.bookmarkedQuestions.add(this.currentQuestionIndex);
      this.elements.bookmarkBtn.classList.add('active');
    }
    this.updateQuestionNavigator();
  }

  updateBookmarkButton() {
    if (this.bookmarkedQuestions.has(this.currentQuestionIndex)) {
      this.elements.bookmarkBtn.classList.add('active');
    } else {
      this.elements.bookmarkBtn.classList.remove('active');
    }
  }

  toggleFullscreen() {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen();
      this.elements.fullscreenBtn.innerHTML = '<i class="fas fa-compress"></i>';
    } else {
      document.exitFullscreen();
      this.elements.fullscreenBtn.innerHTML = '<i class="fas fa-expand"></i>';
    }
  }

  generateQuestionGrid() {
    const grid = this.elements.questionGrid;
    grid.innerHTML = '';
    for (let i = 0; i < this.questions.length; i++) {
      const btn = document.createElement('button');
      btn.className = 'question-number-btn';
      btn.textContent = i + 1;
      btn.addEventListener('click', () => this.goToQuestion(i));
      grid.appendChild(btn);
    }
  }

  updateQuestionNavigator() {
    const buttons = this.elements.questionGrid.querySelectorAll('.question-number-btn');
    buttons.forEach((btn, index) => {
      btn.classList.remove('answered', 'bookmarked', 'current');
      if (index === this.currentQuestionIndex) {
        btn.classList.add('current');
      }
      if (this.userAnswers.hasOwnProperty(index)) {
        btn.classList.add('answered');
      }
      if (this.bookmarkedQuestions.has(index)) {
        btn.classList.add('bookmarked');
      }
    });
  }

  showQuestionNavigator() {
    this.elements.questionNav.classList.remove('hidden');
    this.elements.showNavBtn.style.display = 'none';
  }

  hideQuestionNavigator() {
    this.elements.questionNav.classList.add('hidden');
    this.elements.showNavBtn.style.display = 'flex';
  }

  goToQuestion(index) {
    this.currentQuestionIndex = index;
    this.showQuestion();
    this.updateNavigationButtons();
    this.updateQuestionNavigator();
  }

  showSubmitModal() {
    const answeredQuestions = Object.keys(this.userAnswers).length;
    const minutes = Math.floor(this.timeRemaining / 60);
    const seconds = this.timeRemaining % 60;
    document.getElementById('modal-answered').textContent = `${answeredQuestions}/${this.questions.length}`;
    document.getElementById('modal-time').textContent = `${minutes}:${seconds.toString().padStart(2, '0')}`;
    this.elements.submitModal.classList.remove('hidden');
  }

  hideSubmitModal() {
    this.elements.submitModal.classList.add('hidden');
  }

  submitQuiz() {
    this.endTime = new Date();
    this.calculateScore();
    this.stopTimer();
    this.hideSubmitModal();
    this.showResults();
  }

  autoSubmitQuiz() {
    this.endTime = new Date();
    this.calculateScore();
    this.stopTimer();
    this.showResults();
  }

  calculateScore() {
    this.score = 0;
    this.questions.forEach((question, index) => {
      if (this.userAnswers[index] === question.answer) {
        this.score++;
      }
    });
  }

  showResults() {
    this.showScreen('results');
    const correct = this.score;
    const incorrect = this.questions.length - correct;
    const percentage = Math.round((correct / this.questions.length) * 100);
    const totalTimeTaken = Math.floor((this.endTime - this.startTime) / 1000);
    const minutes = Math.floor(totalTimeTaken / 60);
    const seconds = totalTimeTaken % 60;
    document.getElementById('score-percentage').textContent = `${percentage}%`;
    document.getElementById('correct-answers').textContent = correct;
    document.getElementById('incorrect-answers').textContent = incorrect;
    document.getElementById('time-taken').textContent = `${minutes}:${seconds.toString().padStart(2, '0')}`;
    document.getElementById('accuracy-rate').textContent = `${percentage}%`;
  }

  showReview() {
    this.showScreen('review');
    this.elements.reviewContent.innerHTML = '';
    this.questions.forEach((question, index) => {
      const userAnswer = this.userAnswers[index];
      const isCorrect = userAnswer === question.answer;
      const reviewItem = document.createElement('div');
      reviewItem.classList.add('review-question');
      reviewItem.innerHTML = `
        <div class="review-question-header">
          <span class="review-question-number">Question ${index + 1}</span>
          <span class="review-result ${isCorrect ? 'correct' : 'incorrect'}">
            ${isCorrect ? 'Correct' : 'Incorrect'}
          </span>
        </div>
        <div class="review-question-text">${question.question}</div>
        <div class="review-options">
          ${question.options.map((opt, i) => `
            <div class="review-option
              ${i === question.answer ? 'correct-answer' : ''}
              ${i === userAnswer ? 'user-answer' : ''}">
              ${String.fromCharCode(65 + i)}. ${opt}
            </div>
          `).join('')}
        </div>
      `;
      this.elements.reviewContent.appendChild(reviewItem);
    });
  }

  hideReview() {
    this.showScreen('results');
  }

  restartQuiz() {
    this.currentQuestionIndex = 0;
    this.userAnswers = {};
    this.bookmarkedQuestions.clear();
    this.score = 0;
    this.timeRemaining = 90 * 60;
    this.startTime = null;
    this.endTime = null;
    this.showScreen('start');
  }

  shareResults() {
    const percentage = Math.round((this.score / this.questions.length) * 100);
    const shareText = `I scored ${percentage}% in the RevisionAI Quiz! Try it yourself.`;
    navigator.clipboard.writeText(shareText).then(() => {
      alert('Results copied to clipboard!');
    });
  }

  handleKeyPress(e) {
    if (!this.isQuizActive()) return;
    if (e.key === 'ArrowRight') this.nextQuestion();
    if (e.key === 'ArrowLeft') this.previousQuestion();
  }

  isQuizActive() {
    return this.elements.screens.quiz.classList.contains('active');
  }
}

document.addEventListener('DOMContentLoaded', () => {
  new QuizApp();
});