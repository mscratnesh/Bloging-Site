const activeLabel = document.createElement('label');
activeLabel.innerHTML = 'Active<input name="active" type="hidden" value="0"><input name="active" type="checkbox" value="1" checked>';
activeLabel.style.cssText = 'display:flex;align-items:center;gap:8px;margin:14px 0;font:11px var(--mono);text-transform:uppercase';
const activeInput = activeLabel.querySelector('input');
document.querySelector('.post-form').prepend(activeLabel);
const originalEditPost = window.editPost;
window.editPost = async (id) => {
  await originalEditPost(id);
  activeInput.checked = Boolean((await (await fetch(`/api/admin/posts/${id}`)).json()).active);
};
const originalNewPost = document.querySelector('#new-post');
originalNewPost.addEventListener('click', () => { activeInput.checked = true; });
