export function render(container) {
  let h = '<div class="top-bar"><div class="top-bar-title">Settings</div></div>';
  h += '<div class="card" style="margin:12px 16px;display:flex;align-items:center;gap:12px"><div style="width:44px;height:44px;border-radius:50%;background:linear-gradient(135deg,#0F0F0F,#1a1a2e);display:flex;align-items:center;justify-content:center;color:#C9A84C;font-family:Cormorant Garamond;font-size:20px;font-weight:700">&#9678;</div><div><div style="font-weight:600">Owner</div><div style="font-size:12px;color:#888">Fosved &middot; Owner</div></div></div>';
  h += '<div style="padding:0 16px;margin:16px 0 8px"><div class="section-title">Voice</div></div>';
  h += '<div class="card" style="margin:0 16px"><div class="setting-row"><div><div class="setting-label">Voice Replies</div><div class="setting-desc">Short answers spoken aloud</div></div></div><div class="setting-row"><div><div class="setting-label">Voice: Male</div><div class="setting-desc">ru-RU-DmitryNeural</div></div></div>';
  h += '<div style="padding:0 16px;margin:16px 0 8px"><div class="section-title">Notifications</div></div>';
  h += '<div class="card" style="margin:0 16px"><div class="setting-row"><div><div class="setting-label">Urgent Alerts</div><div class="setting-desc">Telegram + push</div></div><div class="setting-row"><div><div class="setting-label">Market Scan</div><div class="setting-desc">Weekly &middot; Friday</div></div></div>';
  h += '<div style="padding:0 16px;margin:16px 0 8px"><div class="section-title">Integrations</div></div>';
  h += '<div class="card" style="margin:0 16px"><div class="setting-row"><div><div class="setting-label">Telegram</div><div style="font-size:12px;color:#639922">Connected</div></div><div class="setting-row"><div><div class="setting-label">GitHub</div><div style="font-size:12px;color:#639922">Connected</div></div><div class="setting-row"><div><div class="setting-label">Archive Channel</div><div style="font-size:12px;color:#639922">Active</div></div></div>';
  h += '<div style="padding:0 16px;margin:16px 0 8px"><div class="section-title">Security</div></div>';
  h += '<div class="card" style="margin:0 16px;border:1px solid #E24B4A;cursor:pointer" onclick="if(window.tgSendData)window.tgSendData({action:\'lockdown\'})"><div style="color:#E24B4A;font-weight:600;font-size:14px">&#128274; Emergency Lockdown</div><div style="font-size:12px;color:#888;margin-top:2px">Freeze all processes</div></div>';
  container.innerHTML = h;
}
