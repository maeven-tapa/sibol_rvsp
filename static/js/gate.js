(() => {
  const station = document.querySelector('.entry-station');
  const fullscreenButton = document.querySelector('#toggle-fullscreen');
  const fullscreenStatus = document.querySelector('#fullscreen-status');
  function syncFullscreen() {
    const active = document.fullscreenElement === station;
    fullscreenButton.textContent = active ? '⛶ Exit fullscreen' : '⛶ Fullscreen';
    fullscreenButton.setAttribute('aria-pressed', String(active));
    fullscreenStatus.textContent = '';
  }
  fullscreenButton.addEventListener('click', async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else if (station.requestFullscreen && document.fullscreenEnabled) await station.requestFullscreen();
      else throw new Error('Fullscreen is unavailable in this browser. Open the station in Chrome or Edge.');
    } catch (error) { fullscreenStatus.textContent = error.message || 'Fullscreen could not be started.'; }
  });
  document.addEventListener('fullscreenchange', syncFullscreen);
  const form = document.querySelector('#scan-form'), result = document.querySelector('#scan-result');
  const video = document.querySelector('#gate-camera'), cameraStatus = document.querySelector('#camera-status');
  const start = document.querySelector('#start-camera'), stop = document.querySelector('#stop-camera');
  let stream = null, busy = false, frame = null, cameraGeneration = 0;
  let lastCode = '', lastTime = 0;
  const canvas = document.createElement('canvas'), ctx = canvas.getContext('2d', {willReadFrequently:true});
  function message(type, title, detail) {
    result.className = `station-result ${type}`;
    const heading = document.createElement('b'), text = document.createElement('span');
    heading.textContent = title; text.textContent = detail;
    result.replaceChildren(heading, text);
  }
  async function submit(code) {
    code = code.trim().toUpperCase();
    if (busy || !code || (code === lastCode && Date.now() - lastTime < 5000)) return;
    busy = true; lastCode = code; lastTime = Date.now();
    form.querySelector('button').disabled = true;
    document.querySelector('#camera-stage').classList.add('busy');
    document.querySelectorAll('.station-routes>div').forEach(el => el.classList.remove('selected'));
    message('busy', 'Checking pass…', 'Please wait for the station response.');
    try {
      const response = await fetch(form.action, {method:'POST', headers:{'X-CSRFToken':form.elements.csrfmiddlewaretoken.value}, body:new URLSearchParams({code, admin_gate: form.elements.admin_gate.value})});
      if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Session expired. Sign in again and reopen the station.');
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Could not validate this pass.');
      message('success', `${data.name} · ${data.type}`, data.message);
      document.querySelector(`#route-${data.relay}`)?.classList.add('selected');
      form.elements.code.value = '';
    } catch(e) { message('error', 'Entry not confirmed', e.message + ' No automatic retry was sent.'); }
    finally { busy=false; lastTime=Date.now(); form.querySelector('button').disabled=false; document.querySelector('#camera-stage').classList.remove('busy'); form.elements.code.focus({preventScroll:true}); form.elements.code.select(); }
  }
  form.addEventListener('submit', e => { e.preventDefault(); submit(form.elements.code.value); });
  form.elements.code.focus({preventScroll:true});
  function stopCamera() {
    cameraGeneration++;
    if (frame) clearTimeout(frame);
    stream?.getTracks().forEach(track => track.stop()); stream=null; video.srcObject=null;
    document.querySelector('#camera-placeholder').hidden=false;
    start.disabled=false; stop.disabled=true;
    cameraStatus.textContent='Camera off · USB QR reader and manual entry available';
  }
  function detect() {
    if (!stream) return;
    if (!busy && video.readyState >= 2) {
      canvas.width=video.videoWidth; canvas.height=video.videoHeight;
      ctx.drawImage(video,0,0);
      const pixels=ctx.getImageData(0,0,canvas.width,canvas.height);
      const qr=window.jsQR(pixels.data,pixels.width,pixels.height,{inversionAttempts:'dontInvert'});
      if (qr) submit(qr.data);
    }
    frame=setTimeout(detect,180);
  }
  start.addEventListener('click', async () => {
    const generation=++cameraGeneration;
    start.disabled=true;
    try {
      if (!window.jsQR) throw new Error('Camera decoder did not load. Check your connection or use the USB QR reader.');
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('Camera access requires localhost or HTTPS. You can still use a USB QR reader.');
      const opened=await navigator.mediaDevices.getUserMedia({video:{facingMode:'environment',width:{ideal:640},height:{ideal:480}},audio:false});
      if (generation!==cameraGeneration) { opened.getTracks().forEach(t=>t.stop()); return; }
      stream=opened; video.srcObject=stream; await video.play();
      document.querySelector('#camera-placeholder').hidden=true; stop.disabled=false;
      cameraStatus.textContent='Camera scanning · hold one QR pass inside the frame'; detect();
    } catch(e) { stopCamera(); cameraStatus.textContent=`Camera unavailable: ${e.message}`; }
  });
  stop.addEventListener('click',stopCamera);
  window.addEventListener('pagehide',stopCamera);
  document.addEventListener('visibilitychange',()=>{if(document.hidden) stopCamera();});
})();
