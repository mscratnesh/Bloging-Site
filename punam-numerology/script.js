const $ = (selector) => document.querySelector(selector);

async function loadReviews() {
  const reviews = await (await fetch('/api/reviews')).json();
  $('#reviews-empty').hidden = reviews.length > 0;
  const cards = reviews.map((review) => `<article class="review-card"><div class="stars">${'★'.repeat(review.rating)}</div><p>${review.review}</p><span class="who">— ${review.name}</span></article>`);
  $('#review-track').innerHTML = cards.length ? cards.concat(cards).join('') : '';
}

async function loadComments() {
  const comments = await (await fetch('/api/comments?page=general')).json();
  $('#comment-list').innerHTML = comments.length
    ? comments.map((comment) => `<article class="comment-item"><strong>${comment.name}</strong><small>${comment.created_at}</small><p>${comment.comment}</p></article>`).join('')
    : '<p class="empty-state">No comments yet — be the first to say hello.</p>';
}

$('#comment-form')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.target;
  const status = $('#comment-status');
  const data = { page: 'general', name: form.name.value.trim(), comment: form.comment.value.trim() };
  const response = await fetch('/api/comments', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
  const result = await response.json();
  status.textContent = result.message || result.error;
  status.classList.toggle('status-ok', response.ok);
  status.classList.toggle('status-error', !response.ok);
  if (response.ok) form.reset();
});

loadReviews().catch(() => { $('#review-track').innerHTML = '<p class="loading-note">Could not load reviews. Start app.py and refresh.</p>'; });
loadComments().catch(() => { $('#comment-list').innerHTML = '<p class="loading-note">Could not load comments. Start app.py and refresh.</p>'; });
