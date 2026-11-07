const synth = window.speechSynthesis;
let voices = [];
function refreshVoices() { voices = synth ? synth.getVoices() : []; }
refreshVoices();
if (synth) synth.addEventListener('voiceschanged', refreshVoices);

function bindPlayback(root = document) {
  root.querySelectorAll('.playback [data-rate]').forEach(button => {
    if (button.dataset.bound === '1') return;
    button.dataset.bound = '1';
    button.addEventListener('click', async () => {
      const panel = button.closest('.playback');
      const status = panel.querySelector('.audio-status');
      const audio = panel.querySelector('audio');
      document.querySelectorAll('audio').forEach(a => { try { a.pause(); } catch {} });
      if (synth) synth.cancel();
      const rate = Number(button.dataset.rate);
      if (audio && audio.getAttribute('src')) {
        audio.playbackRate = rate;
        audio.currentTime = 0;
        try {
          await audio.play();
          status.textContent = rate < 1 ? 'Playing slowly' : 'Playing normally';
        } catch {
          status.textContent = 'This recording could not play. Try another audio format.';
        }
        return;
      }
      refreshVoices();
      const locale = (panel.dataset.language || '').toLowerCase();
      // Cantonese must never silently fall back to a Mandarin voice.
      const voice = voices.find(v => v.lang.toLowerCase().replace('_', '-') === locale) ||
        (locale === 'yue-hk' ? voices.find(v => v.lang.toLowerCase() === 'zh-hk') : null);
      if (!synth || !locale || !voice) {
        status.textContent = 'No matching voice is installed on this device. Add a speaker recording to hear this word.';
        return;
      }
      const utterance = new SpeechSynthesisUtterance(panel.dataset.text);
      utterance.voice = voice;
      utterance.lang = voice.lang;
      utterance.rate = rate;
      utterance.onend = () => { status.textContent = 'Browser voice'; };
      utterance.onerror = () => { status.textContent = 'Voice playback failed. Try a speaker recording.'; };
      status.textContent = rate < 1 ? 'Speaking slowly' : 'Speaking normally';
      synth.speak(utterance);
    });
  });
}
bindPlayback();

const record = document.querySelector('#record');
const stop = document.querySelector('#stop');
const status = document.querySelector('#record-status');
const input = document.querySelector('#audio');
const preview = document.querySelector('#record-preview');
const manualForm = input ? input.closest('form') : null;
let recorder, stream, chunks = [], timer, previewUrl;
function stopRecording() { if (recorder && recorder.state === 'recording') recorder.stop(); }
record?.addEventListener('click', async () => {
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    status.textContent = 'Recording is unavailable in this browser. Upload an audio file instead.'; return;
  }
  record.disabled = true;
  try {
    stream = await navigator.mediaDevices.getUserMedia({audio: true});
    recorder = new MediaRecorder(stream);
    chunks = [];
    recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
    recorder.onstop = () => {
      clearTimeout(timer);
      stream.getTracks().forEach(track => track.stop());
      const type = recorder.mimeType || 'audio/webm';
      const blob = new Blob(chunks, {type});
      record.disabled = false; stop.disabled = true;
      if (!blob.size || blob.size > 9.5 * 1024 * 1024) {
        status.textContent = 'Recording is empty or too large. Please record a shorter clip.';
        return;
      }
      const ext = type.includes('mp4') ? 'm4a' : type.includes('ogg') ? 'ogg' : 'webm';
      const transfer = new DataTransfer();
      transfer.items.add(new File([blob], 'recording.' + ext, {type}));
      input.files = transfer.files;
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      previewUrl = URL.createObjectURL(blob);
      preview.src = previewUrl;
      preview.hidden = false;
      status.textContent = 'Recording ready. Save the entry to keep it.';
    };
    recorder.start(); stop.disabled = false;
    status.textContent = 'Recording… press Stop when finished (maximum 60 seconds).';
    timer = setTimeout(stopRecording, 60000);
  } catch {
    stream?.getTracks().forEach(track => track.stop());
    record.disabled = false;
    status.textContent = 'Microphone unavailable or permission denied. You can upload a recording instead.';
  }
});
stop?.addEventListener('click', stopRecording);
manualForm?.addEventListener('submit', event => {
  if (record?.disabled) {
    event.preventDefault();
    status.textContent = 'Stop recording before saving.';
  }
});
input?.addEventListener('change', () => {
  preview.hidden = true;
  status.textContent = input.files.length ? 'Audio file selected.' : '';
});
window.addEventListener('pagehide', () => {
  stream?.getTracks().forEach(track => track.stop());
  if (synth) synth.cancel();
});
