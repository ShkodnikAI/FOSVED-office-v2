export function render(container, route) {
  const dept = route.includes('/') ? route.split('/')[2] || 'yana' : 'yana';
  const dn = {yana:'Yana',osp:'OSP',lz:'LZ',expert:'Expert',marketing:'Marketing',finance:'Finance',legal:'Legal',dev:'Dev',design:'Design',qa:'QA',visual:'Visual',engineering:'Engineering',kavalnya:'Kavalnya',admin:'Admin'};
  let h = '<div class="top-bar"><div class="top-bar-title">Chat</div></div>';
  h += '<div style="display:flex;gap:6px;padding:8px 12px;overflow-x:auto;-webkit-overflow-scrolling:touch">';
  Object.keys(dn).forEach(d => {
    const a = d===dept;
    h += '<span class="chip '+(a?'chip-active':'')+'" onclick="location.hash=\'/chat/'+d+'\'" style="white-space:nowrap">'+dn[d]+'</span>';
  });
  h += '</div>';
  h += '<div id="chat-messages" style="flex:1;min-height:200px;padding:8px 0"><div style="text-align:center;padding:40px;color:#aaa;font-size:13px">Start a conversation with '+dn[dept]+'</div></div>';
  h += '<div class="chat-input-bar"><input class="chat-input" id="chat-input" placeholder="Message '+dn[dept]+'..." onkeydown="if(event.key===\'Enter\')window._sendChat()"><button class="chat-send-btn" onclick="window._sendChat()" style="font-size:16px">&#8594;</button></div>';
  container.innerHTML = h;
  window._sendChat = function() {
    const inp = document.getElementById('chat-input');
    const text = inp.value.trim(); if(!text) return; inp.value='';
    const msgs = document.getElementById('chat-messages');
    msgs.innerHTML += '<div class="chat-bubble-user">'+esc(text)+'</div>';
    msgs.innerHTML += '<div class="chat-bubble-ai"><div style="font-size:12px;color:#C9A84C;margin-bottom:4px;font-weight:500">'+dn[dept]+'</div>This screen requires the Telegram bot for responses. Use the bot chat or send commands directly.</div>';
    msgs.scrollTop = msgs.scrollHeight;
  };
}
function esc(t){const d=document.createElement('div');d.textContent=t;return d.innerHTML;}
