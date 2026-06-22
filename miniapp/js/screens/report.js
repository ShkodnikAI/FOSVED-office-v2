export async function render(container, id) {
  try {
    const resp = await fetch('/miniapp/' + id);
    if (!resp.ok) { container.innerHTML = '<div class="empty-state">Report not found</div>'; return; }
    container.innerHTML = await resp.text();
  } catch(e) { container.innerHTML = '<div class="empty-state">Failed to load report</div>'; }
}
