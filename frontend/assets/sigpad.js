/* Create-signature dialog shared by the Document Centre editor and the public
   signing page: Type (handwriting styles) / Draw / Upload image / Camera.
   SigCreator.open({kind:'signature'|'initials', name, allowSave}) resolves to
   {blob, dataUrl, saved} or null if cancelled. Everything is drawn into a
   transparent PNG in the browser; the server re-encodes it again anyway. */
(function(){
  'use strict';
  const FONTS = ['Dancing Script','Great Vibes','Allura','Sacramento','Alex Brush','Parisienne','Satisfy',
                 'Yellowtail','Mr Dafoe','Herr Von Muellerhoff','Homemade Apple','Caveat','La Belle Aurore','Kaushan Script'];
  const COLORS = ['#4f6ee8','#2c4fa3','#3a2df0','#0000ff','#5c5c5c','#333333','#000000'];
  const CSS = `
  .sg-ov{position:fixed; inset:0; background:rgba(21,20,26,.55); z-index:300; display:flex; align-items:center; justify-content:center; padding:16px;}
  .sg{background:#fff; color:#15141a; width:760px; max-width:100%; max-height:calc(100vh - 32px); overflow:auto; border-radius:22px; box-shadow:0 24px 60px rgba(0,0,0,.3); font-family:Inter,system-ui,sans-serif;}
  .sg-head{display:flex; align-items:center; justify-content:space-between; padding:18px 22px; border-bottom:1px solid #eae6db;}
  .sg-head h2{font:600 17px 'Space Grotesk',Inter,sans-serif;}
  .sg-x{width:32px; height:32px; border-radius:100px; border:none; background:#f2efe8; color:#3a3846; font-size:16px; cursor:pointer;}
  .sg-tabs{display:flex; gap:4px; padding:12px 22px 0; border-bottom:1px solid #eae6db; flex-wrap:wrap; align-items:flex-end;}
  .sg-tab{border:1px solid transparent; border-bottom:none; background:none; padding:10px 14px; border-radius:12px 12px 0 0; font:600 13px Inter,sans-serif; color:#8b8894; cursor:pointer; display:flex; gap:7px; align-items:center;}
  .sg-tab svg{width:17px; height:17px;}
  .sg-tab.on{color:#15141a; border-color:#eae6db; background:#fff; margin-bottom:-1px;}
  .sg-save{margin-left:auto; display:flex; gap:7px; align-items:center; font-size:12.5px; font-weight:600; padding-bottom:10px;}
  .sg-body{padding:20px 22px;}
  .sg-in{width:100%; max-width:420px; display:block; margin:0 auto 14px; background:#f2efe8; border:1px solid #eae6db; border-radius:10px; padding:11px 13px; font-size:15px;}
  .sg-colors{display:flex; gap:10px; justify-content:center; margin-bottom:16px;}
  .sg-c{width:26px; height:26px; border-radius:50%; border:3px solid #fff; box-shadow:0 0 0 1px #d6d0c0; cursor:pointer;}
  .sg-c.on{box-shadow:0 0 0 2px #15141a;}
  .sg-fonts{display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:8px;}
  .sg-f{border:1px solid #eae6db; background:#fff; border-radius:12px; padding:10px; height:74px; font-size:30px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; cursor:pointer; line-height:1.4;}
  .sg-f.on{background:#eef4ff; border-color:#9db6f5;}
  .sg-pad{width:100%; height:230px; border:1px dashed #cfc8b6; border-radius:14px; touch-action:none; cursor:crosshair; display:block; background:#fff;}
  .sg-row{display:flex; justify-content:space-between; align-items:center; margin-top:10px; gap:10px; flex-wrap:wrap;}
  .sg-prev{min-height:140px; border:1px dashed #cfc8b6; border-radius:14px; display:flex; align-items:center; justify-content:center; padding:12px; background:repeating-conic-gradient(#f6f4ee 0 25%, #fff 0 50%) 0 0/18px 18px;}
  .sg-prev img{max-width:100%; max-height:200px;}
  .sg-note{font-size:11.5px; color:#8b8894; text-align:center; margin-top:14px;}
  .sg-foot{display:flex; justify-content:flex-end; gap:8px; padding:0 22px 20px;}
  .sg-btn{border-radius:100px; padding:10px 20px; font:600 13px Inter,sans-serif; cursor:pointer; border:1px solid #eae6db; background:#fff; color:#3a3846;}
  .sg-btn.go{background:#15141a; color:#d7f26d; border:none;}
  .sg-btn:disabled{opacity:.45; cursor:not-allowed;}
  .sg-err{color:#a13d20; font-size:12.5px; text-align:center; min-height:18px; margin-top:8px;}
  .sg-lbl{display:inline-flex; align-items:center; gap:7px; font-size:12.5px; font-weight:600;}
  @media (max-width:560px){ .sg-tab span{display:none;} .sg-f{font-size:24px;} }`;
  const ICON = {
    type:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="2.5" y="6" width="19" height="12" rx="2"/><path d="M6 10h1M9 10h1M12 10h1M15 10h1M18 10h0.5M7 14h10"/></svg>',
    draw:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 17c3-6 5-9 7-9s0 8 2 8 3-5 5-5 2 3 4 3"/></svg>',
    upload:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="4" y="3" width="16" height="18" rx="2"/><circle cx="9.5" cy="9" r="1.6"/><path d="M5 18l5-5 3 3 2-2 4 4"/></svg>',
    camera:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/></svg>',
  };
  let fontsLinked = false;
  function linkFonts(){
    if(fontsLinked) return; fontsLinked = true;
    const l = document.createElement('link'); l.rel = 'stylesheet';
    l.href = 'https://fonts.googleapis.com/css2?' + FONTS.map(f => 'family=' + f.replace(/ /g, '+')).join('&') + '&display=swap';
    document.head.appendChild(l);
    const st = document.createElement('style'); st.textContent = CSS; document.head.appendChild(st);
  }
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  // Trim transparent margins and cap the size.
  function trimCanvas(src){
    const ctx = src.getContext('2d'), {width:w, height:h} = src, d = ctx.getImageData(0, 0, w, h).data;
    let x0 = w, y0 = h, x1 = -1, y1 = -1;
    for(let y = 0; y < h; y++) for(let x = 0; x < w; x++) if(d[(y * w + x) * 4 + 3] > 8){ if(x < x0) x0 = x; if(x > x1) x1 = x; if(y < y0) y0 = y; if(y > y1) y1 = y; }
    if(x1 < 0) return null;
    const pad = 4, cw = x1 - x0 + 1 + pad * 2, ch = y1 - y0 + 1 + pad * 2;
    const k = Math.min(1, 1600 / Math.max(cw, ch));
    const out = document.createElement('canvas'); out.width = Math.round(cw * k); out.height = Math.round(ch * k);
    out.getContext('2d').drawImage(src, x0 - pad, y0 - pad, cw, ch, 0, 0, out.width, out.height);
    return out;
  }
  // Photo / scan of ink on paper -> transparent background, keeping the ink colour.
  function knockOut(img, strength){
    const k = Math.min(1, 2000 / Math.max(img.naturalWidth, img.naturalHeight));
    const c = document.createElement('canvas'); c.width = Math.round(img.naturalWidth * k); c.height = Math.round(img.naturalHeight * k);
    const ctx = c.getContext('2d'); ctx.drawImage(img, 0, 0, c.width, c.height);
    const im = ctx.getImageData(0, 0, c.width, c.height), d = im.data;
    // paper brightness = a high percentile of luminance
    const hist = new Uint32Array(256);
    for(let i = 0; i < d.length; i += 16) hist[Math.round(0.299 * d[i] + 0.587 * d[i+1] + 0.114 * d[i+2])]++;
    let total = 0; for(const v of hist) total += v;
    let acc = 0, paper = 255; for(let v = 255; v >= 0; v--){ acc += hist[v]; if(acc > total * 0.35){ paper = v; break; } }
    const hi = paper - 18 * strength, lo = Math.max(0, paper - 110);
    for(let i = 0; i < d.length; i += 4){
      const L = 0.299 * d[i] + 0.587 * d[i+1] + 0.114 * d[i+2];
      const a = L >= hi ? 0 : L <= lo ? 1 : (hi - L) / (hi - lo);
      d[i+3] = Math.round(a * (d[i+3] / 255) * 255);
      if(a > 0){ const f = 0.75; d[i] *= f; d[i+1] *= f; d[i+2] *= f; }
    }
    ctx.putImageData(im, 0, 0);
    return c;
  }
  const toBlob = c => new Promise(r => c.toBlob(r, 'image/png'));

  function open(opts){
    opts = opts || {};
    linkFonts();
    const kind = opts.kind === 'initials' ? 'initials' : 'signature';
    const defName = kind === 'initials'
      ? (opts.name || '').split(/\s+/).filter(Boolean).map(w => w[0].toUpperCase()).join('').slice(0, 4)
      : (opts.name || '');
    return new Promise(resolve => {
      const ov = document.createElement('div'); ov.className = 'sg-ov';
      ov.innerHTML = `<div class="sg" role="dialog" aria-modal="true" aria-label="Create ${kind}">
        <div class="sg-head"><h2>Create ${kind}</h2><button class="sg-x" aria-label="Close">✕</button></div>
        <div class="sg-tabs">
          <button class="sg-tab on" data-t="type">${ICON.type}<span>Type</span></button>
          <button class="sg-tab" data-t="draw">${ICON.draw}<span>Draw</span></button>
          <button class="sg-tab" data-t="upload">${ICON.upload}<span>Upload Image</span></button>
          <button class="sg-tab" data-t="camera">${ICON.camera}<span>Camera</span></button>
          ${opts.allowSave === false ? '' : `<label class="sg-save"><input type="checkbox" class="sg-keep" checked> Save ${kind}</label>`}
        </div>
        <div class="sg-body"></div>
        <div class="sg-err" role="alert"></div>
        <div class="sg-foot"><button class="sg-btn sg-cancel">Cancel</button><button class="sg-btn go sg-ok">Save</button></div>
      </div>`;
      document.body.appendChild(ov);
      const body = ov.querySelector('.sg-body'), err = ov.querySelector('.sg-err');
      let tab = 'type', color = COLORS[6], font = FONTS[0], typed = defName, padDirty = false, photo = null, strength = 1;
      let pad = null;

      function colorRow(){
        return `<div class="sg-colors">${COLORS.map(c => `<button class="sg-c ${c === color ? 'on' : ''}" data-c="${c}" style="background:${c}" aria-label="Colour ${c}"></button>`).join('')}</div>`;
      }
      function bindColors(after){
        body.querySelectorAll('.sg-c').forEach(b => b.onclick = () => { color = b.dataset.c; body.querySelectorAll('.sg-c').forEach(x => x.classList.toggle('on', x === b)); after && after(); });
      }
      function render(){
        err.textContent = '';
        ov.querySelectorAll('.sg-tab').forEach(t => t.classList.toggle('on', t.dataset.t === tab));
        if(tab === 'type'){
          body.innerHTML = `<input class="sg-in" maxlength="60" placeholder="Type your ${kind === 'initials' ? 'initials' : 'name'}" value="${esc(typed)}">${colorRow()}
            <div class="sg-fonts">${FONTS.map(f => `<button class="sg-f ${f === font ? 'on' : ''}" data-f="${f}" style="font-family:'${f}',cursive; color:${color}">${esc(typed || 'Your name')}</button>`).join('')}</div>`;
          const inp = body.querySelector('.sg-in');
          inp.oninput = () => { typed = inp.value; body.querySelectorAll('.sg-f').forEach(b => b.textContent = typed || 'Your name'); };
          setTimeout(() => { inp.focus(); inp.select(); }, 30);
          bindColors(() => body.querySelectorAll('.sg-f').forEach(b => b.style.color = color));
          body.querySelectorAll('.sg-f').forEach(b => b.onclick = () => { font = b.dataset.f; body.querySelectorAll('.sg-f').forEach(x => x.classList.toggle('on', x === b)); });
        } else if(tab === 'draw'){
          body.innerHTML = colorRow() + `<canvas class="sg-pad"></canvas><div class="sg-row"><span class="sg-note" style="margin:0;">Sign with your mouse, trackpad, finger or stylus</span><button class="sg-btn sg-clear">Clear</button></div>`;
          pad = body.querySelector('.sg-pad'); padDirty = false;
          const r = pad.getBoundingClientRect(), dpr = Math.min(window.devicePixelRatio || 1, 3);
          pad.width = r.width * dpr; pad.height = r.height * dpr;
          const ctx = pad.getContext('2d'); ctx.scale(dpr, dpr); ctx.lineCap = 'round'; ctx.lineJoin = 'round';
          let down = false, last = null;
          const pt = e => { const b = pad.getBoundingClientRect(); return [e.clientX - b.left, e.clientY - b.top, e.pressure || 0.5]; };
          pad.onpointerdown = e => { down = true; pad.setPointerCapture(e.pointerId); last = pt(e); ctx.fillStyle = color; ctx.beginPath(); ctx.arc(last[0], last[1], 1.4, 0, 7); ctx.fill(); padDirty = true; };
          pad.onpointermove = e => { if(!down) return; const p = pt(e); ctx.strokeStyle = color; ctx.lineWidth = 1.6 + 2.2 * (e.pointerType === 'pen' ? p[2] : 0.5); ctx.beginPath(); ctx.moveTo(last[0], last[1]); ctx.lineTo(p[0], p[1]); ctx.stroke(); last = p; };
          pad.onpointerup = pad.onpointercancel = () => { down = false; };
          body.querySelector('.sg-clear').onclick = () => { ctx.clearRect(0, 0, pad.width, pad.height); padDirty = false; };
          bindColors();
        } else {
          const cam = tab === 'camera';
          body.innerHTML = `<div class="sg-prev">${photo ? '<img alt="Preview">' : `<span class="sg-note" style="margin:0;">${cam ? 'Sign on a sheet of white paper, then take a clear, well-lit photo of it.' : 'Choose a picture of your signature (PNG, JPG). A transparent PNG works best.'}</span>`}</div>
            <div class="sg-row"><label class="sg-btn" style="cursor:pointer;">${cam ? 'Take photo' : 'Choose image'}<input type="file" accept="image/*" ${cam ? 'capture="environment"' : ''} hidden class="sg-file"></label>
            <span class="sg-lbl"><label class="sg-lbl"><input type="checkbox" class="sg-bg" ${strength ? 'checked' : ''}> Remove paper background</label>
            <select class="sg-str" ${strength ? '' : 'disabled'}><option value="1">Normal</option><option value="2" ${strength === 2 ? 'selected' : ''}>Stronger</option></select></span></div>`;
          const showPrev = () => {
            if(!photo) return;
            const c = strength ? knockOut(photo, strength) : (() => { const x = document.createElement('canvas'); x.width = photo.naturalWidth; x.height = photo.naturalHeight; x.getContext('2d').drawImage(photo, 0, 0); return x; })();
            body._canvas = c; body.querySelector('.sg-prev img').src = c.toDataURL('image/png');
          };
          body.querySelector('.sg-file').onchange = e => {
            const f = e.target.files[0]; if(!f) return;
            const im = new Image(); im.onload = () => { photo = im; render(); showPrev(); }; im.onerror = () => { err.textContent = 'That image could not be opened.'; };
            im.src = URL.createObjectURL(f);
          };
          body.querySelector('.sg-bg').onchange = e => { strength = e.target.checked ? (+body.querySelector('.sg-str').value || 1) : 0; render(); showPrev(); };
          body.querySelector('.sg-str').onchange = e => { strength = +e.target.value; showPrev(); };
          if(photo) showPrev();
        }
      }
      async function build(){
        if(tab === 'type'){
          const text = typed.trim();
          if(!text) throw new Error(`Type your ${kind === 'initials' ? 'initials' : 'name'} first.`);
          await document.fonts.load(`80px "${font}"`).catch(() => {});
          const c = document.createElement('canvas'), ctx = c.getContext('2d'), size = 110;
          ctx.font = `${size}px "${font}"`;
          const w = Math.ceil(ctx.measureText(text).width) + size;
          c.width = Math.min(w, 3000); c.height = Math.round(size * 2);
          ctx.font = `${size}px "${font}"`; ctx.fillStyle = color; ctx.textBaseline = 'middle';
          ctx.fillText(text, size / 2, c.height / 2);
          return trimCanvas(c);
        }
        if(tab === 'draw'){
          if(!padDirty) throw new Error('Draw your ' + kind + ' in the box first.');
          return trimCanvas(pad);
        }
        if(!body._canvas) throw new Error(tab === 'camera' ? 'Take a photo of your signature first.' : 'Choose an image first.');
        return trimCanvas(body._canvas);
      }
      const close = v => { ov.remove(); document.removeEventListener('keydown', onKey); resolve(v); };
      const onKey = e => { if(e.key === 'Escape') close(null); };
      document.addEventListener('keydown', onKey);
      ov.addEventListener('click', e => { if(e.target === ov) close(null); });
      ov.querySelector('.sg-x').onclick = ov.querySelector('.sg-cancel').onclick = () => close(null);
      ov.querySelectorAll('.sg-tab').forEach(t => t.onclick = () => { tab = t.dataset.t; render(); });
      ov.querySelector('.sg-ok').onclick = async () => {
        const btn = ov.querySelector('.sg-ok'); btn.disabled = true;
        try {
          const c = await build();
          if(!c) throw new Error('Nothing to save - the ' + kind + ' is empty.');
          const keep = ov.querySelector('.sg-keep');
          close({blob: await toBlob(c), dataUrl: c.toDataURL('image/png'), saved: keep ? keep.checked : false, ratio: c.width / c.height});
        } catch(e){ err.textContent = e.message; btn.disabled = false; }
      };
      render();
    });
  }
  window.SigCreator = {open, FONTS, COLORS};
})();
