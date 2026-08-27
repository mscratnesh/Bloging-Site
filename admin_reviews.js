const reviewStatus = document.querySelector('.status');
const reviewQueue = document.createElement('section');
reviewQueue.className = 'saved-posts';
reviewQueue.innerHTML = '<h2>Customer reviews</h2><div id="review-list"></div>';
document.querySelector('main').append(reviewQueue);

async function loadReviewQueue() {
  const response = await fetch('/api/admin/reviews');
  if (!response.ok) return;
  const reviews = await response.json();
  document.querySelector('#review-list').innerHTML = reviews.map((review) => `<div class="saved-item"><div><strong>${review.name}</strong><small>${review.status} · ${'★'.repeat(review.rating)}</small><p>${review.review}</p></div><div class="saved-buttons">${review.status === 'pending' ? `<button data-review="${review.id}" data-status="approved">Approve</button><button data-review="${review.id}" data-status="rejected">Reject</button>` : ''}</div></div>`).join('');
  document.querySelectorAll('[data-review]').forEach((button) => button.addEventListener('click', async () => {
    const result = await (await fetch(`/api/admin/reviews/${button.dataset.review}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: button.dataset.status }) })).json();
    reviewStatus.textContent = result.message || result.error;
    loadReviewQueue();
  }));
}

loadReviewQueue();
