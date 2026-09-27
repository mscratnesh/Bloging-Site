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

document.querySelectorAll('.nav-group').forEach((group) => {
  const toggle = group.querySelector('.nav-toggle');
  toggle.addEventListener('click', (event) => {
    event.stopPropagation();
    const open = group.classList.toggle('is-open');
    toggle.setAttribute('aria-expanded', String(open));
  });
});

const closeNavGroups = () => document.querySelectorAll('.nav-group.is-open').forEach((group) => {
  group.classList.remove('is-open');
  group.querySelector('.nav-toggle').setAttribute('aria-expanded', 'false');
});
document.addEventListener('click', (event) => { if (!event.target.closest('.nav-group')) closeNavGroups(); });
document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeNavGroups(); });
