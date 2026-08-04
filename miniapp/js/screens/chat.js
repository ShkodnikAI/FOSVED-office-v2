/**
 * FOSVED Mini App — Chat Screen (/chat/:slug)
 */

import { esc } from '../app.js';
import { formatRating, getDeptDisplayName } from '../api.js';

// Dept colors for chips
const DEPT_COLORS = {
  yana: '#C9A84C',
  osp: '#dc2626',
  lz: '#0891b2',
  marketing: '#ea580c',
  finansy: '#16a34a',
  razrabotka: '#2563eb',
  design: '#ec4899',
  qa: '#4d7c0f',
  visual: '#a855f7',
  engineering: '#44403c',
  kavalnya: '#b45309',
  expert: '#4f46e5',
  'tekhnicheskiy-preparator': '#0ea5e9',
  legal: '#475569',
};

export async function render(container, params) {
  const slug = params?.slug || 'yana';
  let data;
  try { data = await API.dept(slug); }
  catch (e) { container.innerHTML = `<div class="empty-state">⚠️ Ошибка загрузки</div>`; return; }

  if (data.status !== 'ok') { container.innerHTML = `<div class="empty-state">⚠️ ${esc(data.error)}</div>`; return; }

  const { name, status, color, commands = [] } = data;
  const displayName = getDeptDisplayName({ name });
  const shortName = displayName.includes(' — ') ? displayName.split(' — ')[0] : displayName;
  const isOnline = status === 'active';
  const deptColor = color?.accent || DEPT_COLORS[slug] || '#888';

  // Get all depts for chips
  let allDepts = [];
  try {
    const deptsData = await API.depts();
    allDepts = deptsData.depts || [];
  } catch (e) {}

  // Mock messages (replace with real API later)
  const messages = [
    { type: 'ai', text: `Здравствуйте! Я ${shortName}. Чем могу помочь?`, time: '14:30' },
  ];

  function render() {
    let html = '';

    // Topbar
    html += `<div class="topbar">`;
    html += `<span class="topbar-back" data-nav="/depts">←</span>`;
    html += `<div class="topbar-avatar" style="background:linear-gradient(135deg,${esc(color?.start||deptColor)},${esc(color?.end||deptColor)})">${esc(shortName.charAt(0))}</div>`;
    html += `<div class="topbar-info"><div class="topbar-name">${esc(displayName)}</div><div class="topbar-status">${isOnline?'● онлайн':'○ offline'}</div></div>`;
    html += `<span class="topbar-more">⋮</span>`;
    html += `</div>`;

    // Dept chips
    html += `<div class="chips-row">`;
    for (const d of allDepts) {
      const dColor = d.color?.accent || DEPT_COLORS[d.slug] || '#888';
      const dName = getDeptDisplayName(d);
      const dShort = dName.includes(' — ') ? dName.split(' — ')[0] : dName;
      const isActive = d.slug === slug;
      html += `<div class="dept-chip${isActive?' active':''}" data-nav="/chat/${esc(d.slug)}" style="border-color:${esc(dColor)};color:${isActive?'var(--c-main)':esc(dColor)}">${esc(dShort)}</div>`;
    }
    html += `</div>`;

    // Messages
    html += `<div class="messages" id="chat-messages">`;
    for (const m of messages) {
      if (m.type === 'ai') {
        html += `<div class="msg-row ai">`;
        html += `<div class="msg-avatar" style="background:linear-gradient(135deg,${esc(color?.start||deptColor)},${esc(color?.end||deptColor)})">${esc(shortName.charAt(0))}</div>`;
        html += `<div class="msg ai"><div>${esc(m.text)}</div><div class="msg-time">${esc(m.time)}</div></div>`;
        html += `</div>`;
      } else {
        html += `<div class="msg-row user">`;
        html += `<div class="msg-avatar" style="background:linear-gradient(135deg,#C9A84C,#b8943f);color:#0F0F0F">Вы</div>`;
        html += `<div class="msg user"><div>${esc(m.text)}</div><div class="msg-time">${esc(m.time)}</div></div>`;
        html += `</div>`;
      }
    }
    html += `</div>`;

    // Quick replies (commands)
    if (commands.length) {
      html += `<div class="quick-replies">`;
      for (const cmd of commands.slice(0, 6)) {
        html += `<button class="quick-btn" data-cmd="${esc(cmd.cmd)}">${esc(cmd.cmd)}</button>`;
      }
      html += `</div>`;
    }

    // Input bar
    html += `<div class="input-bar">`;
    html += `<button class="attach-btn" id="attach-btn" title="Прикрепить файл">+</button>`;
    html += `<input type="text" id="chat-input" placeholder="Напишите сообщение...">`;
    html += `<button class="mic-btn" id="mic-btn" title="Голосовое сообщение">🎤</button>`;
    html += `<button class="send-btn" id="send-btn">↑</button>`;
    html += `<input type="file" id="file-input" style="display:none" accept="image/*,video/*,.pdf,.doc,.docx,.txt">`;
    html += `</div>`;

    container.innerHTML = html;

    // Wire up events
    const input = container.querySelector('#chat-input');
    const sendBtn = container.querySelector('#send-btn');
    const attachBtn = container.querySelector('#attach-btn');
    const fileInput = container.querySelector('#file-input');
    const micBtn = container.querySelector('#mic-btn');
    const msgsDiv = container.querySelector('#chat-messages');

    function addMessage(text, type, fileName = null) {
      const time = new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
      let msgHtml = '';
      if (type === 'user') {
        msgHtml += `<div class="msg-row user">`;
        msgHtml += `<div class="msg-avatar" style="background:linear-gradient(135deg,#C9A84C,#b8943f);color:#0F0F0F">Вы</div>`;
        if (fileName) {
          msgHtml += `<div class="msg user"><div>📎 <b>${esc(fileName)}</b></div><div class="msg-time">${esc(time)}</div></div>`;
        } else {
          msgHtml += `<div class="msg user"><div>${esc(text)}</div><div class="msg-time">${esc(time)}</div></div>`;
        }
        msgHtml += `</div>`;
      } else {
        msgHtml += `<div class="msg-row ai">`;
        msgHtml += `<div class="msg-avatar" style="background:linear-gradient(135deg,${esc(color?.start||deptColor)},${esc(color?.end||deptColor)})">${esc(shortName.charAt(0))}</div>`;
        msgHtml += `<div class="msg ai"><div>${esc(text)}</div><div class="msg-time">${esc(time)}</div></div>`;
        msgHtml += `</div>`;
      }
      msgsDiv.insertAdjacentHTML('beforeend', msgHtml);
      msgsDiv.scrollTop = msgsDiv.scrollHeight;
    }

    function speakText(text) {
      const ttsEnabled = localStorage.getItem('fosved_tts_yana') !== '0';
      if (!ttsEnabled || !window.speechSynthesis) return;
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = 'ru-RU';
      const speed = parseFloat(localStorage.getItem('fosved_tts_speed') || '1');
      utterance.rate = speed;
      window.speechSynthesis.speak(utterance);
    }


    function send() {
      const text = input.value.trim();
      if (!text) return;
      addMessage(text, 'user');
      input.value = '';
      // Mock AI response
      setTimeout(() => {
        addMessage('Принято. Обрабатываю запрос...', 'ai');
        speakText('Принято. Обрабатываю запрос.');
      }, 500);
    }

    sendBtn.addEventListener('click', send);
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') send(); });

    attachBtn.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', (e) => {
      const file = e.target.files[0];
      if (file) {
        addMessage(null, 'user', file.name);
        setTimeout(() => {
          addMessage(`✓ Файл «${file.name}» получен. Передал в отдел для обработки.`, 'ai');
        }, 500);
      }
      fileInput.value = '';
    });

    // Mic button
    let recording = false;
    micBtn.addEventListener('click', () => {
      recording = !recording;
      micBtn.classList.toggle('recording', recording);
      if (recording) {
        micBtn.textContent = '⏹';
        addMessage('🎤 Запись голосового сообщения...', 'user');
      } else {
        micBtn.textContent = '🎤';
        setTimeout(() => {
          addMessage('✓ Голосовое сообщение отправлено.', 'ai');
        }, 300);
      }
    });

    // Quick reply buttons
    container.querySelectorAll('.quick-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        input.value = btn.dataset.cmd + ' ';
        input.focus();
      });
    });

    // Scroll to bottom
    msgsDiv.scrollTop = msgsDiv.scrollHeight;
  }

  render();
}
