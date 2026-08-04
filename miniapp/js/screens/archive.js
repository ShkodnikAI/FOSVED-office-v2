/**
 * FOSVED Mini App — Archive Screen (/archive)
 */

import { esc } from '../app.js';
import { formatRating } from '../api.js';

export async function render(container) {
  let data;
  try { data = await API.archive(); }
  catch (e) { container.innerHTML = `<div class="empty-state">⚠️ Ошибка загрузки</div>`; return; }

  if (data.status !== 'ok') { container.innerHTML = `<div class="empty-state">⚠️ ${esc(data.error)}</div>`; return; }

  const results = data.results || [];

  // Group by year → month
  const years = {};
  for (const r of results) {
    const date = r.date || '—';
    const parts = date.split('.');
    const year = parts.length >= 3 ? parts[2] : '—';
    const month = parts.length >= 2 ? parts[1] : '—';
    const monthNames = { '01':'Январь','02':'Февраль','03':'Март','04':'Апрель','05':'Май','06':'Июнь','07':'Июль','08':'Август','09':'Сентябрь','10':'Октябрь','11':'Ноябрь','12':'Декабрь' };
    const monthName = monthNames[month] || month;
    if (!years[year]) years[year] = {};
    if (!years[year][monthName]) years[year][monthName] = [];
    years[year][monthName].push(r);
  }

  let html = `<div class="topbar"><div class="topbar-title">Архив</div></div>`;
  html += `<div class="screen-scroll">`;

  if (Object.keys(years).length) {
    for (const [year, months] of Object.entries(years)) {
      html += `<div class="year-header">${esc(year)}</div>`;
      for (const [month, items] of Object.entries(months)) {
        html += `<div class="month-header">${esc(month)}</div>`;
        for (const r of items) {
          const rating = formatRating(r.rating);
          const control = r.control ? ' control' : '';
          const forecastPct = r.forecast_pct ?? null;
          let forecastBadge = '';
          if (forecastPct !== null) {
            const fcClass = forecastPct >= 80 ? '' : forecastPct >= 50 ? ' low' : ' bad';
            const fcIcon = forecastPct >= 80 ? '✓' : '⚠';
            forecastBadge = `<span class="badge-forecast${fcClass}">${fcIcon} ${forecastPct}% прогноза</span>`;
          }
          const controlBadge = r.control ? `<span class="badge-control">⚠ НА КОНТРОЛЕ</span>` : '';
          const checkDate = r.check_date || '—';
          const checkClass = r.control ? '' : ' ok';

          html += `
            <div class="archive-card${control}" data-nav="/report/${esc(r.id)}">
              <div class="archive-header">
                <span class="archive-title">${esc(r.title)}</span>
                <div class="archive-badges">
                  ${controlBadge}
                  ${forecastBadge}
                </div>
              </div>
              <div class="archive-meta">
                <span class="archive-dept" style="background:${esc(r.dept_color || '#888')}">${esc(r.dept || '—')}</span>
                <span class="archive-date">${esc(r.date)}</span>
                <span class="archive-check${checkClass}">проверка: ${esc(checkDate)}</span>
                <span class="archive-depth">глубина ${esc(r.depth || '—')}</span>
              </div>
              <div class="archive-desc">${esc(r.description || '—')}</div>
            </div>`;
        }
      }
    }
  } else {
    html += `<div class="empty-state">Архив пуст</div>`;
  }

  html += `</div>`;
  container.innerHTML = html;
}
