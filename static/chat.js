const widget = document.querySelector('.chat-widget');
if (widget) {
  const toggle = widget.querySelector('.chat-toggle');
  const panel = widget.querySelector('.chat-panel');
  const log = widget.querySelector('.chat-log');
  const form = widget.querySelector('.chat-form');
  const input = form.querySelector('input');
  const history = [];

  function addMessage(role, text) {
    const item = document.createElement('p');
    item.className = role === 'user' ? 'chat-user' : 'chat-assistant';
    item.textContent = text;
    log.appendChild(item);
    log.scrollTop = log.scrollHeight;
  }

  toggle.addEventListener('click', () => {
    const open = panel.hidden;
    panel.hidden = !open;
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (open) input.focus();
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const question = input.value.trim();
    if (!question) return;
    addMessage('user', question);
    history.push({ role: 'user', content: question });
    input.value = '';
    const button = form.querySelector('button');
    button.disabled = true;
    try {
      const response = await fetch(widget.dataset.endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, history: history.slice(0, -1).slice(-6) }),
      });
      const data = await response.json();
      const reply = data.reply || data.error || 'Could not answer just now.';
      addMessage('assistant', reply);
      if (data.reply) history.push({ role: 'assistant', content: data.reply });
    } catch {
      addMessage('assistant', 'Could not reach the tutor. Try again.');
    } finally {
      button.disabled = false;
      input.focus();
    }
  });
}
