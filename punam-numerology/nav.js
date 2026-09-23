document.querySelectorAll('.menu').forEach((button) => {
  button.setAttribute('aria-expanded', 'false');
  button.addEventListener('click', () => {
    const header = button.closest('.site-header');
    const open = header.classList.toggle('nav-open');
    button.classList.toggle('is-open', open);
    button.setAttribute('aria-expanded', String(open));
  });
});

document.querySelectorAll('.site-header nav a').forEach((link) => {
  link.addEventListener('click', () => {
    const header = link.closest('.site-header');
    header.classList.remove('nav-open');
    header.querySelector('.menu')?.classList.remove('is-open');
  });
});
