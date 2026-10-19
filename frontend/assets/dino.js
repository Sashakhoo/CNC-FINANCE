/* Loading screen: a little pixel dinosaur hopping over cacti.
   Dino.show('Loading…') / Dino.hide(). Shown only if loading takes longer
   than a moment, so fast loads never flash. Respects reduced motion. */
(function(){
  'use strict';
  const BODY = [
    '          ########',
    '         ## #######',
    '         ##########',
    '         ##########',
    '         #####',
    '         ########',
    '#       #####',
    '#     ########',
    '##   #########',
    '###  ######## #',
    '############',
    ' ###########',
    '  #########',
    '   #######',
  ];
  const LEGS_A = ['    ### ##', '    ##   #', '    #    ##', '    ##'];
  const LEGS_B = ['    ### ##', '    #   ##', '    ##   #', '         ##'];
  const CACTUS = ['  ##', '  ##  #', '# ##  #', '# ## ##', '####', '  ##', '  ##', '  ##'];
  const rects = (rows, dy) => rows.map((r, y) => [...r].map((ch, x) => ch === '#' ? `<rect x="${x}" y="${y + (dy || 0)}" width="1" height="1"/>` : '').join('')).join('');

  const CSS = `
  .dino-ov{position:fixed; inset:0; z-index:500; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:18px;
    background:rgba(242,239,232,.92); backdrop-filter:blur(3px); -webkit-backdrop-filter:blur(3px); opacity:0; transition:opacity .18s ease;}
  .dino-ov.on{opacity:1;}
  .dino-stage{position:relative; width:min(420px, calc(100vw - 48px)); height:130px; overflow:hidden; border-bottom:2px solid #15141a;}
  .dino-stage::after{content:''; position:absolute; left:0; right:0; bottom:4px; height:2px;
    background:repeating-linear-gradient(90deg,#8b8894 0 6px,transparent 6px 22px); animation:dino-ground .6s linear infinite;}
  .dino{position:absolute; left:34px; bottom:2px; width:80px; height:72px; fill:#15141a; animation:dino-jump 1.5s infinite;}
  .dino .legs-b{display:none;}
  .dino.run .legs-a{animation:dino-step .2s steps(1) infinite;}
  .dino.run .legs-b{display:block; animation:dino-step .2s steps(1) infinite reverse;}
  .dino-cactus{position:absolute; bottom:2px; left:100%; width:30px; height:56px; fill:#3a4408; animation:dino-cactus 1.5s linear infinite;}
  .dino-cactus.c2{width:22px; height:42px; margin-left:34px;}
  .dino-sun{position:absolute; top:12px; right:30px; width:22px; height:22px; border-radius:50%; background:#d7f26d; box-shadow:0 0 0 6px rgba(215,242,109,.35);}
  .dino-msg{font:600 16px 'Space Grotesk',Inter,sans-serif; color:#15141a; letter-spacing:-.2px; text-align:center;}
  .dino-sub{font:500 12.5px Inter,sans-serif; color:#8b8894; margin-top:-12px; text-align:center; min-height:16px;}
  @keyframes dino-jump{0%,54%,90%,100%{transform:translateY(0)} 68%{transform:translateY(-64px)} 77%{transform:translateY(-58px)}}
  @keyframes dino-cactus{0%{transform:translateX(0)} 100%{transform:translateX(calc(-1 * min(420px, calc(100vw - 48px)) - 80px))}}
  @keyframes dino-step{0%{opacity:1} 50%{opacity:0}}
  @keyframes dino-ground{from{background-position:0 0} to{background-position:-22px 0}}
  @media (prefers-color-scheme:dark){ :root:not([data-theme="light"]) .dino-ov{background:rgba(242,239,232,.95);} }
  @media (prefers-reduced-motion:reduce){ .dino, .dino-cactus, .dino-stage::after, .dino.run .legs-a, .dino.run .legs-b{animation:none;} .dino-cactus{left:180px;} .dino .legs-b{display:none;} }`;
  const TIPS = ['Hopping over a few cacti…', 'Fetching your numbers…', 'Almost there…', 'Still working — big files take a moment'];
  let el = null, timer = null, tipTimer = null, depth = 0;

  function build(){
    if(el) return el;
    const st = document.createElement('style'); st.textContent = CSS; document.head.appendChild(st);
    el = document.createElement('div'); el.className = 'dino-ov'; el.setAttribute('role', 'status'); el.setAttribute('aria-live', 'polite');
    el.innerHTML = `<div class="dino-stage" aria-hidden="true"><span class="dino-sun"></span>
        <svg class="dino run" viewBox="0 0 20 18" shape-rendering="crispEdges">${rects(BODY)}<g class="legs-a">${rects(LEGS_A, 14)}</g><g class="legs-b">${rects(LEGS_B, 14)}</g></svg>
        <svg class="dino-cactus" viewBox="0 0 7 8" shape-rendering="crispEdges">${rects(CACTUS)}</svg>
        <svg class="dino-cactus c2" viewBox="0 0 7 8" shape-rendering="crispEdges">${rects(CACTUS)}</svg></div>
      <div class="dino-msg"></div><div class="dino-sub"></div>`;
    return el;
  }
  function show(msg, delay){
    depth++;
    build();
    el.querySelector('.dino-msg').textContent = msg || 'Loading…';
    el.querySelector('.dino-sub').textContent = '';
    if(el.isConnected || timer) return;
    timer = setTimeout(() => {
      timer = null;
      document.body.appendChild(el);
      requestAnimationFrame(() => el.classList.add('on'));
      let i = 0;
      tipTimer = setInterval(() => { el.querySelector('.dino-sub').textContent = TIPS[i++ % TIPS.length]; }, 2600);
    }, delay === undefined ? 220 : delay);
  }
  function hide(force){
    depth = force ? 0 : Math.max(0, depth - 1);
    if(depth > 0) return;
    clearTimeout(timer); timer = null; clearInterval(tipTimer);
    if(el && el.isConnected){ el.classList.remove('on'); setTimeout(() => { if(depth === 0 && el.isConnected) el.remove(); }, 200); }
  }
  async function wrap(promise, msg){ show(msg); try { return await promise; } finally { hide(); } }
  window.Dino = {show, hide, wrap};
})();
