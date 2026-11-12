/* Barra común para las pantallas anteriores (expedientes, nuevo expediente, medición). */
(() => {
  const here = location.pathname;
  const links = [['/', 'Inicio'], ['/#nuevo', 'Nuevo estimado'], ['/#entregas', 'Entregas'], ['/expedientes', 'Expedientes'], ['/herramientas', 'Medición en planos'], ['/#admin', 'Administrador']];
  const bar = document.createElement('nav');
  bar.setAttribute('aria-label', 'ALKAN Bid Engine');
  bar.style.cssText = 'display:flex;flex-wrap:wrap;gap:4px;align-items:center;background:#0c3136;padding:6px 12px;font:13px system-ui,sans-serif';
  for (const [href, text] of links) {
    const a = document.createElement('a');
    const on = href === here || (href === '/expedientes' && (here === '/' || here === '/nuevo'));
    a.href = href; a.textContent = text;
    a.style.cssText = 'text-decoration:none;padding:5px 10px;border-radius:6px;' + (on ? 'background:#fff;color:#103e43;font-weight:600' : 'color:#d5e6e4');
    bar.appendChild(a);
  }
  document.body.insertBefore(bar, document.body.firstChild);
})();
