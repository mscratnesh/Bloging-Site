// WhatsApp chat link in every public page's top menu. Number: country code + number, digits only.
const WHATSAPP_NUMBER = '91XXXXXXXXXX';
document.querySelectorAll('.site-header nav').forEach((nav) => {
  const link = document.createElement('a');
  link.className = 'nav-whatsapp';
  link.href = `https://wa.me/${WHATSAPP_NUMBER}`;
  link.target = '_blank';
  link.rel = 'noopener';
  link.innerHTML = '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"><path fill="currentColor" d="M12 2a10 10 0 0 0-8.6 15.1L2 22l5-1.3A10 10 0 1 0 12 2Zm0 18.2a8.2 8.2 0 0 1-4.2-1.2l-.3-.2-3 .8.8-2.9-.2-.3A8.2 8.2 0 1 1 12 20.2Zm4.5-6.1c-.2-.1-1.5-.7-1.7-.8-.2-.1-.4-.1-.6.1l-.8 1c-.1.2-.3.2-.5.1a6.7 6.7 0 0 1-3.3-2.9c-.2-.4.2-.4.7-1.3.1-.2 0-.3 0-.4l-.8-1.8c-.2-.5-.4-.4-.6-.4h-.5a1 1 0 0 0-.7.3 3 3 0 0 0-.9 2.2 5.2 5.2 0 0 0 1.1 2.7 11.8 11.8 0 0 0 4.5 4c1.7.7 2.3.8 3.2.6.5-.1 1.5-.6 1.7-1.2.2-.6.2-1.1.2-1.2-.1-.1-.3-.2-.5-.3Z"/></svg>WhatsApp';
  nav.append(link);
});

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
