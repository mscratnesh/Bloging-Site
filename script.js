const state = { posts: [], filter: 'all', query: '' };
const $ = (selector) => document.querySelector(selector);

function renderFeatured(post) {
  $('#featured-image').style.backgroundImage = `url('${post.image_url}')`;
  $('#featured-category').textContent = `${post.category} · ${post.published_at}`;
  $('#featured-title').textContent = post.title;
  $('#featured-summary').textContent = post.summary;
  $('#featured-author').textContent = `By ${post.author}`;
  $('#featured-initials').textContent = post.initials;
  $('#featured-link').href = `post.html?id=${post.id}`;
}

function renderPosts() {
  const visible = state.posts.filter((post) => {
    const categoryMatch = state.filter === 'all' || post.category === state.filter;
    const searchMatch = post.title.toLowerCase().includes(state.query);
    return categoryMatch && searchMatch && post.image_class !== 'featured';
  });
  $('#post-grid').innerHTML = visible.map((post) => `<article class="post-card"><div class="post-image image-${post.image_class}" style="background-image:url('${post.image_url}')"></div><p class="category">${post.category} · ${post.published_at}</p><h3>${post.title}</h3><p>${post.summary}</p><a href="post.html?id=${post.id}" class="post-link">Read note <span>↗</span></a></article>`).join('');
  $('#empty-state').hidden = visible.length > 0;
}

async function loadPosts() {
  const response = await fetch('/api/posts');
  state.posts = await response.json();
  renderFeatured(state.posts.find((post) => post.image_class === 'featured'));
  renderPosts();
}

async function loadReviews() {
  const reviews = await (await fetch('/api/reviews')).json();
  $('#reviews-empty').hidden = reviews.length > 0;
  const cards = reviews.map((review) => {
    const shot = review.image_url ? `<a class="review-shot" href="${review.image_url}" target="_blank" rel="noopener"><img src="${review.image_url}" alt="Screenshot of feedback from ${review.name}" loading="lazy"></a>` : '';
    const text = review.review ? `<p>${review.review}</p>` : '';
    return `<article class="review-card"><div class="stars">${'★'.repeat(review.rating)}</div>${shot}${text}<span class="who">— ${review.name}</span></article>`;
  });
  $('#review-track').innerHTML = cards.length ? cards.concat(cards).join('') : '';
}

document.querySelectorAll('.topic-tabs button').forEach((button) => button.addEventListener('click', () => {
  document.querySelectorAll('.topic-tabs button').forEach((item) => item.classList.remove('active'));
  button.classList.add('active'); state.filter = button.dataset.filter; renderPosts();
}));
$('#search').addEventListener('input', (event) => { state.query = event.target.value.trim().toLowerCase(); renderPosts(); });
loadPosts().catch(() => { $('#post-grid').innerHTML = '<p class="loading-note">Could not load insights. Start app.py and refresh.</p>'; });
loadReviews().catch(() => { $('#review-track').innerHTML = '<p class="loading-note">Could not load reviews. Start app.py and refresh.</p>'; });
