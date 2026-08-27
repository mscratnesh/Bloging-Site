function addShareControl() {
  const article = document.querySelector('#article-content');
  const heading = article.querySelector('.article-head');
  if (!heading || document.querySelector('.share-control')) return;
  const wrapper = document.createElement('div');
  wrapper.className = 'share-control';
  wrapper.style.cssText = 'display:flex;align-items:center;gap:12px;margin-top:22px';
  wrapper.innerHTML = '<button type="button" style="border:1px solid var(--ink);background:transparent;color:var(--ink);padding:10px 15px;font:11px var(--mono);cursor:pointer">Share article ↗</button><span style="color:var(--muted);font:10px var(--mono)" aria-live="polite"></span>';
  heading.append(wrapper);
  const button = wrapper.querySelector('button');
  const message = wrapper.querySelector('span');
  button.addEventListener('click', async () => {
    const shareData = { title: document.title, text: heading.querySelector('h1').textContent, url: window.location.href };
    try {
      if (navigator.share) await navigator.share(shareData);
      else {
        await navigator.clipboard.writeText(window.location.href);
        message.textContent = 'Link copied.';
        return;
      }
      message.textContent = 'Thanks for sharing.';
    } catch (error) {
      if (error.name !== 'AbortError') message.textContent = 'Could not share this link.';
    }
  });
}

const articleObserver = new MutationObserver(addShareControl);
articleObserver.observe(document.querySelector('#article-content'), { childList: true });
