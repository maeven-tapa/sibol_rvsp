(() => {
  const station = document.querySelector('.entry-station');
  const mobile = station.dataset.mobile === 'true';
  // Keep the original entry-log tab aware of this scanner, including after reloads.
  function notifyEntryTab() {
    if (window.opener && !window.opener.closed) {
      window.opener.postMessage({type: 'sibol-scanner-open'}, window.location.origin);
    }
  }
  notifyEntryTab();
  const entryHeartbeat = setInterval(notifyEntryTab, 1000);
  window.addEventListener('pagehide', () => clearInterval(entryHeartbeat));
  const fullscreenButton = document.querySelector('#toggle-fullscreen');
  const fullscreenStatus = document.querySelector('#fullscreen-status');
  function syncFullscreen() {
    const active = document.fullscreenElement === station;
    if (!fullscreenButton) return;
    fullscreenButton.textContent = active ? '⛶ Exit fullscreen' : '⛶ Fullscreen';
    fullscreenButton.setAttribute('aria-pressed', String(active));
    fullscreenStatus.textContent = '';
  }
  fullscreenButton?.addEventListener('click', async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else if (station.requestFullscreen && document.fullscreenEnabled) await station.requestFullscreen();
      else throw new Error('Fullscreen is unavailable in this browser. Open the station in Chrome or Edge.');
    } catch (error) { fullscreenStatus.textContent = error.message || 'Fullscreen could not be started.'; }
  });
  document.addEventListener('fullscreenchange', syncFullscreen);
  const form = document.querySelector('#scan-form'), result = document.querySelector('#camera-placeholder');
  const video = document.querySelector('#gate-camera'), cameraStatus = document.querySelector('#camera-status');
  const start = document.querySelector('#start-camera'), stop = document.querySelector('#stop-camera');
  let stream = null, busy = false, frame = null, cameraGeneration = 0;
  let lastCode = '', lastTime = 0;
  const canvas = document.createElement('canvas'), ctx = canvas.getContext('2d', {willReadFrequently:true});
  const defaultPlaceholder = [...result.childNodes].map(node => node.cloneNode(true));
  let resultTimer = null, routeTimer = null, showingResult = false;
  function clearResult() {
    clearTimeout(resultTimer);
    clearTimeout(routeTimer);
    showingResult = false;
    result.className = 'camera-placeholder';
    result.replaceChildren(...defaultPlaceholder.map(node => node.cloneNode(true)));
    result.hidden = Boolean(stream);
    document.querySelector('#camera-stage').classList.remove('has-result');
    document.querySelectorAll('.station-routes>div').forEach(el => el.classList.remove('selected'));
  }
  function message(type, title, detail, data = {}) {
    clearTimeout(resultTimer);
    showingResult = true;
    result.hidden = false;
    result.className = `camera-placeholder scan-feedback ${type}`;
    document.querySelector('#camera-stage').classList.add('has-result');
    const icon = document.createElement('span'); icon.className = 'scan-feedback-icon';
    icon.textContent = {success:'✓', exit:'⇥', error:'✕', warning:'!', busy:'…'}[type];
    icon.setAttribute('aria-hidden', 'true');
    const heading = document.createElement('b'); heading.textContent = title;
    result.replaceChildren(icon, heading);
    if (data.name) { const name = document.createElement('div'); name.className = 'scan-person'; name.textContent = data.name; result.append(name); }
    if (data.type) { const kind = document.createElement('small'); kind.textContent = `${data.type} ticket`; result.append(kind); }
    const text = document.createElement('small'); text.textContent = detail; result.append(text);
    if (type !== 'busy') resultTimer = setTimeout(clearResult, 1500);
  }
  async function submit(code, camera = false) {
    code = code.trim().toUpperCase();
    if (busy || !code || (camera && code === lastCode)) return;
    busy = true; lastCode = code; lastTime = Date.now();
    form.querySelector('button').disabled = true;
    document.querySelector('#camera-stage').classList.add('busy');
    document.querySelectorAll('.station-routes>div').forEach(el => el.classList.remove('selected'));
    message('busy', 'Checking pass…', 'Please wait for the station response.');
    try {
      const response = await fetch(form.action, {method:'POST', headers:{'X-CSRFToken':form.elements.csrfmiddlewaretoken.value}, body:new URLSearchParams({code, ...(mobile ? {mobile: '1'} : {})})});
      if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Session expired. Sign in again and reopen the station.');
      const data = await response.json();
      if (!response.ok) {
        const duplicate = response.status === 409;
        document.querySelectorAll('.station-routes>div').forEach(el => el.classList.remove('selected'));
        const title = duplicate ? (data.admission_pending ? 'Admission needs inspection' : data.exited ? 'Already exited' : 'Already entered') : 'Invalid ticket';
        const detail = duplicate && data.entry_time
          ? `${data.admission_pending ? 'Attempt recorded' : 'Entered'}: ${data.entry_time}${data.admission_pending ? '. Ask the administrator to inspect the gate.' : ''}`
          : data.error || 'Could not validate this pass.';
        message(duplicate ? 'warning' : 'error', title, detail, data);
        return;
      }
      message(data.direction === 'exit' ? 'exit' : 'success', data.direction === 'exit' ? 'Exit successful' : data.admitted ? 'Access granted' : 'Valid reservation', data.message, data);
      (data.gates || [data.gate]).forEach(gate => document.querySelector(`#route-${gate}`)?.classList.add('selected'));
      routeTimer = setTimeout(() => {
        document.querySelectorAll('.station-routes>div').forEach(el => el.classList.remove('selected'));
      }, 1500);
      form.elements.code.value = '';
    } catch(e) { message('error', 'Entry not confirmed', e.message + ' No automatic retry was sent.'); }
    finally { busy=false; lastTime=Date.now(); form.querySelector('button').disabled=false; document.querySelector('#camera-stage').classList.remove('busy'); if (!mobile) { form.elements.code.focus({preventScroll:true}); form.elements.code.select(); } }
  }
  form.addEventListener('submit', e => { e.preventDefault(); submit(form.elements.code.value); });
  if (!mobile) form.elements.code.focus({preventScroll:true});
  function stopCamera() {
    cameraGeneration++;
    if (frame) clearTimeout(frame);
    stream?.getTracks().forEach(track => track.stop()); stream=null; video.srcObject=null;
    document.querySelector('#camera-placeholder').hidden=false;
    if (start) start.disabled=false; if (stop) stop.disabled=true;
    cameraStatus.textContent=mobile ? 'Camera off · manual entry available' : 'Camera off · USB QR reader and manual entry available';
  }
  function detect() {
    if (!stream) return;
    if (!busy && !showingResult && video.readyState >= 2) {
      canvas.width=video.videoWidth; canvas.height=video.videoHeight;
      ctx.drawImage(video,0,0);
      const pixels=ctx.getImageData(0,0,canvas.width,canvas.height);
      const qr=window.jsQR(pixels.data,pixels.width,pixels.height,{inversionAttempts:'dontInvert'});
      if (qr) submit(qr.data, true);
      else { lastCode = ''; lastTime = 0; }
    }
    frame=setTimeout(detect,180);
  }
  async function startCamera() {
    if (stream) return;
    const generation=++cameraGeneration;
    if (start) start.disabled=true;
    try {
      if (!window.jsQR) throw new Error(mobile ? 'Camera decoder did not load. Check your connection or enter the ticket code.' : 'Camera decoder did not load. Check your connection or use the USB QR reader.');
      if (!navigator.mediaDevices?.getUserMedia) throw new Error(mobile ? 'Camera access requires HTTPS. Open the secure site or enter the ticket code below.' : 'Camera access requires localhost or HTTPS. You can still use a USB QR reader.');
      const opened=await navigator.mediaDevices.getUserMedia({video:{facingMode:'environment',width:{ideal:640},height:{ideal:480}},audio:false});
      if (generation!==cameraGeneration) { opened.getTracks().forEach(t=>t.stop()); return; }
      stream=opened; video.srcObject=stream; await video.play();
      if (generation!==cameraGeneration) return;
      clearResult(); if (stop) stop.disabled=false;
      cameraStatus.textContent='Camera scanning · hold one QR pass inside the frame'; detect();
    } catch(e) { if (generation!==cameraGeneration) return; stopCamera(); cameraStatus.textContent=`Camera unavailable: ${e.message}`; }
  }
  start?.addEventListener('click', startCamera);
  stop?.addEventListener('click',stopCamera);
  if (mobile && !document.hidden) startCamera();
  window.addEventListener('pageshow', event => { if (mobile && event.persisted && !document.hidden) startCamera(); });
  window.addEventListener('pagehide',stopCamera);
  document.addEventListener('visibilitychange',()=>{if(document.hidden) stopCamera(); else if (mobile) startCamera();});
})();
