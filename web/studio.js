const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const $ = selector => document.querySelector(selector);
const svgNS = 'http://www.w3.org/2000/svg';

export function setupStudio({api, toast, fail, showExport, getTray}) {
  let project=null, scene=null, selected=null, mode='compose', connected=false;
  let timer, visible=false, loading=false, editing=false, generation=0, lastSignature='', pendingRequest=false;
  const root=$('#studio');
  root.innerHTML=`
    <div class="studio-toolbar"><div><button id="studioBack" class="plain">← 라이브러리</button><h1 id="projectTitle">제작실</h1></div><div class="studio-tools"><select id="projectPicker" aria-label="저장한 도해"><option value="">저장한 도해</option></select><button class="secondary" id="studioNew">트레이로 새 도해</button><button class="primary" id="studioExport" disabled>내보내기 ↗</button></div></div>
    <div class="studio-body"><aside class="studio-assets"><div class="nav-label">선택한 재료</div><div id="studioAssets"></div><p>원본 파일은<br>그대로 보존됩니다.</p></aside>
    <div class="studio-work"><div class="canvas-toolbar"><span id="canvasKind">새 도해</span><span id="canvasRevision"></span><select id="versionPicker" aria-label="결과 버전" hidden></select><div class="canvas-actions"><button id="addText" class="secondary" disabled>텍스트 +</button><button id="addArrow" class="secondary" disabled>화살표 +</button></div></div>
    <div class="canvas-area"><div id="canvasEmpty" class="studio-empty"><span class="studio-empty-mark">↗</span><h2>재료에서 한 장의 그림으로</h2><p>클립아트를 선택하고, 만들고 싶은 그림을 설명하세요.</p><button class="secondary" id="emptyLibrary">클립아트 고르기</button></div><div id="figureCanvas" hidden><img id="figurePreview" alt="제작 중인 도해"><svg id="figureHandles" viewBox="0 0 1400 850" aria-label="도해 요소 선택과 이동"></svg></div></div>
    <div class="canvas-foot"><span id="canvasHint">구도 · 라벨 · 연결선 · 이미지 생성</span><span>과학적 내용은 사용 전 확인하세요.</span></div>
    <div id="elementEditor" class="element-editor" hidden></div></div>
    <aside class="studio-chat"><div class="chat-heading"><h2>제작 대화</h2><button id="codexRefresh" class="plain" title="Codex 연결 새로고침">↻</button></div>
    <div class="codex-connection"><span id="codexStatus">Codex 연결 확인 중…</span><button id="codexLogin" class="secondary" hidden>ChatGPT 로그인</button><a id="loginLink" target="_blank" rel="noreferrer" hidden>브라우저에서 로그인 ↗</a></div>
    <div id="chatMessages" class="chat-messages" role="log" aria-label="제작 대화"></div>
    <div id="jobStatus" class="job-status" role="status" hidden></div>
    <form id="studioComposer"><div class="mode-switch" role="group" aria-label="제작 방식"><button type="button" data-mode="compose" class="active" aria-pressed="true">원본 조합</button><button type="button" data-mode="image" aria-pressed="false">AI 이미지</button></div><p id="modeDescription">원본 클립아트와 편집 가능한 라벨·화살표로 구성합니다.</p><textarea id="studioPrompt" rows="4" maxlength="6000" aria-label="그림 제작 요청" placeholder="이 그림으로 무엇을 설명하고 싶으세요?"></textarea><div class="composer-actions"><small>Codex 구독 사용량에 포함</small><button type="button" id="cancelJob" class="secondary" hidden>취소</button><button id="sendPrompt" class="primary" disabled>만들기 ↑</button></div></form></aside></div>`;

  function activeJob(){return project?.jobs.find(j=>['running','queued'].includes(j.status));}
  function close(){visible=false;generation++;clearTimeout(timer);root.hidden=true;document.body.classList.remove('studio-open');$('#sceneButton').focus();}
  $('#studioBack').onclick=close;$('#emptyLibrary').onclick=close;
  async function projectList(){
    const items=await api('/api/studio/projects');
    $('#projectPicker').innerHTML='<option value="">저장한 도해</option>'+items.map(p=>`<option value="${p.id}">${escape(p.title)}</option>`).join('');
    if(project)$('#projectPicker').value=project.id;
    return items;
  }
  async function newProject(){
    const ids=getTray();
    if(!ids.length||ids.length>8){toast('라이브러리 트레이에 클립아트 1–8개를 담아 주세요.');return;}
    const p=await api('/api/studio/projects',{file_ids:ids});
    await loadProject(p.id);await projectList();
  }
  $('#studioNew').onclick=()=>newProject().catch(fail);
  $('#projectPicker').onchange=e=>{if(e.target.value)loadProject(e.target.value).catch(fail);};
  async function connection(){
    try{
      const result=await api('/api/codex/status');connected=result.connected;
      $('#codexStatus').textContent=connected?'● Codex 연결됨 · ChatGPT 구독':result.error|| (result.auth_type==='apiKey'?'API 키 연결됨 · 구독 로그인이 필요합니다':'ChatGPT 구독을 연결하세요');
      $('#codexLogin').hidden=connected||!result.available;
      if(connected)$('#loginLink').hidden=true;
    }catch(e){connected=false;$('#codexStatus').textContent=e.message;}
    controls();
  }
  $('#versionPicker').onchange=async e=>{
    try{project=await api(`/api/studio/projects/${project.id}/version`,{scene_id:e.target.value});scene=await api('/api/scenes/'+project.scene_id);selected=null;setMode(scene?.generated_image?'image':'compose');lastSignature=JSON.stringify(project);renderProject();renderCanvas();}catch(error){fail(error);}
  };
  $('#codexRefresh').onclick=connection;
  $('#codexLogin').onclick=async()=>{
    try{const result=await api('/api/codex/login',{});const link=$('#loginLink');link.href=result.url;link.hidden=false;link.click();$('#codexStatus').textContent='브라우저에서 로그인 후 연결이 완료됩니다.';}catch(e){fail(e);}
  };
  function controls(){
    const running=!!activeJob()||pendingRequest;
    $('#sendPrompt').disabled=!connected||!project||running||!$('#studioPrompt').value.trim();
    $('#sendPrompt').textContent=scene?'수정하기 ↑':'만들기 ↑';
    $('#cancelJob').hidden=!activeJob();
    $('#studioExport').disabled=!scene||running||editing;
    $('#studioNew').disabled=running;
    $('#projectPicker').disabled=running;
    $('#versionPicker').disabled=running||editing;
    $('#addText').disabled=!scene||running||editing;
    $('#addArrow').disabled=!scene||running||editing;
    $('#elementEditor').querySelectorAll('input,button').forEach(el=>el.disabled=running||editing);
  }
  function renderProject(){
    $('#projectTitle').textContent=project?.title||'제작실';
    if(project)$('#projectPicker').value=project.id;
    $('#studioAssets').innerHTML=(project?.file_ids||[]).map(id=>`<figure><img src="/api/preview/${id}" alt="선택한 파일 ${id}"><figcaption>${id}</figcaption></figure>`).join('');
    const box=$('#chatMessages');const atBottom=box.scrollHeight-box.scrollTop-box.clientHeight<70;
    box.innerHTML=project?.messages.length?project.messages.map(m=>`<div class="chat-message ${m.role}"><small>${m.role==='user'?'나':'BioArt'}</small><p>${escape(m.text)}</p></div>`).join(''):`<div class="chat-welcome"><h3>어떤 그림을 만들까요?</h3><p>선택한 재료로 과정, 비교, 구조를 설명해 보세요.</p><button class="example-prompt">선택한 그림의 관계를 보여주는 도해를 만들어줘.</button></div>`;
    box.querySelector('.example-prompt')?.addEventListener('click',e=>{$('#studioPrompt').value=e.target.textContent;controls();$('#studioPrompt').focus();});
    if(atBottom)box.scrollTop=box.scrollHeight;
    const versions=(project?.jobs||[]).filter(j=>j.status==='completed'&&j.scene_id);
    $('#versionPicker').hidden=versions.length<2;
    $('#versionPicker').innerHTML=versions.map((j,i)=>`<option value="${j.scene_id}">${i+1} · ${j.mode==='compose'?'원본 조합':'AI 이미지'}</option>`).join('');
    if(project?.scene_id)$('#versionPicker').value=project.scene_id;
    const job=project?.jobs.at(-1);const status=$('#jobStatus');
    status.hidden=!job||job.status==='completed';
    status.classList.toggle('job-error',!!job?.error);
    status.textContent=job?(job.error||job.progress||job.status):'';
    controls();
  }
  async function loadProject(pid){
    const seq=++generation;loading=true;
    try{
      const p=await api('/api/studio/projects/'+pid);
      const s=p.scene_id?await api('/api/scenes/'+p.scene_id):null;
      if(seq!==generation)return;
      project=p;scene=s;selected=null;setMode(scene?.generated_image?'image':'compose');lastSignature=JSON.stringify(p);renderProject();renderCanvas();
    }finally{loading=false;}
  }
  async function tick(){
    if(!visible)return;
    try{
      if(project&&!loading&&!editing&&!pendingRequest){
        const pid=project.id, seq=generation;
        const p=await api('/api/studio/projects/'+pid);
        if(seq===generation&&JSON.stringify(p)!==lastSignature){
          lastSignature=JSON.stringify(p);const oldScene=project.scene_id;project=p;renderProject();
          if(p.scene_id!==oldScene){scene=await api('/api/scenes/'+p.scene_id);selected=null;renderCanvas();await projectList();}
        }
      }
      if(!connected)await connection();
    }catch(e){$('#jobStatus').hidden=false;$('#jobStatus').textContent='연결 확인 중 · '+e.message;}
    finally{if(visible)timer=setTimeout(tick,1800);}
  }
  function setMode(value){
    mode=value;
    root.querySelectorAll('[data-mode]').forEach(b=>{const active=b.dataset.mode===mode;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));});
    $('#modeDescription').textContent=mode==='compose'?'원본 클립아트와 편집 가능한 라벨·화살표로 구성합니다.':'클립아트를 참고해 새로 그립니다. 원본 구조가 달라질 수 있습니다.';
  }
  root.querySelectorAll('[data-mode]').forEach(button=>button.onclick=()=>setMode(button.dataset.mode));
  $('#studioPrompt').oninput=controls;
  $('#studioComposer').onsubmit=async e=>{
    e.preventDefault();if($('#sendPrompt').disabled)return;
    const prompt=$('#studioPrompt').value.trim();pendingRequest=true;controls();
    try{
      project=await api(`/api/studio/projects/${project.id}/messages`,{prompt,mode});
      $('#studioPrompt').value='';lastSignature=JSON.stringify(project);renderProject();$('#chatMessages').scrollTop=$('#chatMessages').scrollHeight;
    }catch(error){fail(error);}finally{pendingRequest=false;controls();}
  };
  $('#studioPrompt').onkeydown=e=>{if((e.metaKey||e.ctrlKey)&&e.key==='Enter'){e.preventDefault();$('#studioComposer').requestSubmit();}};
  $('#cancelJob').onclick=async()=>{const job=activeJob();if(!job)return;$('#cancelJob').disabled=true;try{project=await api(`/api/studio/projects/${project.id}/cancel/${job.id}`,{});renderProject();}catch(e){fail(e);}finally{$('#cancelJob').disabled=false;}};
  $('#studioExport').onclick=async()=>{try{showExport(await api(`/api/studio/projects/${project.id}/export`,{}));}catch(e){fail(e);}};

  function elements(){return scene?[...scene.objects.map(o=>({...o,kind:'asset'})),...(scene.texts||[]).map(o=>({...o,kind:'text'})),...(scene.arrows||[]).map(o=>({...o,kind:'arrow'}))]:[];}
  function fitCanvas(){
    const area=root.querySelector('.canvas-area');
    const styles=getComputedStyle(area);
    const width=area.clientWidth-parseFloat(styles.paddingLeft)-parseFloat(styles.paddingRight);
    const height=area.clientHeight-parseFloat(styles.paddingTop)-parseFloat(styles.paddingBottom);
    const figure=$('#figureCanvas');
    figure.style.width=Math.max(0,Math.min(width,height*1400/850))+'px';
    figure.style.height=Math.max(0,Math.min(height,width*850/1400))+'px';
  }
  new ResizeObserver(fitCanvas).observe(root.querySelector('.canvas-area'));
  function renderCanvas(){
    $('#canvasEmpty').hidden=!!scene;$('#figureCanvas').hidden=!scene;
    $('#canvasKind').textContent=scene?(scene.generated_image?'AI 생성 이미지 · 라벨 편집 가능':'원본 클립아트 도해'):'새 도해';
    $('#canvasRevision').textContent=scene?'수정 '+scene.revision:'';
    $('#canvasHint').textContent=scene?'요소를 선택해 끌거나 아래에서 값을 수정하세요.':'구도 · 라벨 · 연결선 · 이미지 생성';
    if(scene){
      $('#figurePreview').src=`/api/scenes/${scene.scene_id}/preview?r=${scene.revision}`;
      renderHandles();
    }
    renderEditor();controls();requestAnimationFrame(fitCanvas);
  }
  function renderHandles(){
    const svg=$('#figureHandles');svg.replaceChildren();
    for(const el of elements()){
      const group=document.createElementNS(svgNS,'g');group.dataset.id=el.id;group.classList.add('figure-handle');if(selected===el.id)group.classList.add('selected');
      let x,y,w,h;
      if(el.kind==='asset'){({x,y,width:w,height:h}=el);h+=46;}
      else if(el.kind==='text'){x=el.x;y=el.y-el.font_size;w=Math.max(40,el.text.length*el.font_size*.8);h=el.font_size+8;}
      else{x=Math.min(el.x1,el.x2)-12;y=Math.min(el.y1,el.y2)-12;w=Math.max(24,Math.abs(el.x2-el.x1)+24);h=Math.max(24,Math.abs(el.y2-el.y1)+24);}
      const rect=document.createElementNS(svgNS,'rect');for(const [k,v]of Object.entries({x,y,width:w,height:h,rx:5}))rect.setAttribute(k,v);group.append(rect);svg.append(group);
      group.onpointerdown=e=>beginDrag(e,el,group);
      group.setAttribute('tabindex','0');group.setAttribute('role','button');group.setAttribute('aria-label',el.label||el.text||el.id);
      group.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();selected=el.id;renderHandles();renderEditor();}};
    }
  }
  function beginDrag(event,el,group){
    if(activeJob()||editing)return;event.preventDefault();selected=el.id;
    $('#figureHandles').querySelectorAll('.figure-handle').forEach(g=>g.classList.toggle('selected',g===group));renderEditor();
    const rect=$('#figureHandles').getBoundingClientRect();const start={x:event.clientX,y:event.clientY};let dx=0,dy=0;
    group.setPointerCapture(event.pointerId);
    group.onpointermove=e=>{dx=(e.clientX-start.x)*1400/rect.width;dy=(e.clientY-start.y)*850/rect.height;group.setAttribute('transform',`translate(${dx} ${dy})`);};
    group.onpointerup=async()=>{
      group.onpointermove=null;group.onpointerup=null;
      if(Math.abs(dx)+Math.abs(dy)<2){renderHandles();return;}
      let patch;
      if(el.kind==='arrow')patch={x1:el.x1+dx,y1:el.y1+dy,x2:el.x2+dx,y2:el.y2+dy};
      else patch={x:el.x+dx,y:el.y+dy};
      for(const key in patch)patch[key]=Math.round(patch[key]*10)/10;
      await changeElement(el,patch);renderHandles();
    };
    group.onpointercancel=()=>{group.onpointermove=null;renderHandles();};
  }
  async function saveScene(patch){
    editing=true;controls();
    try{scene=await api('/api/scenes/'+scene.scene_id,{revision:scene.revision,patches:{},...patch});renderCanvas();}
    catch(e){fail(e);scene=await api('/api/scenes/'+scene.scene_id);renderCanvas();}
    finally{editing=false;controls();}
  }
  async function changeElement(el,patch){
    if(el.kind==='asset')await saveScene({patches:{[el.id]:patch}});
    else{const key=el.kind==='arrow'?'arrows':'texts';await saveScene({[key]:scene[key].map(o=>o.id===el.id?{...o,...patch}:o)});}
  }
  function renderEditor(){
    const editor=$('#elementEditor'), el=elements().find(o=>o.id===selected);editor.hidden=!el;if(!el)return;
    const fields=el.kind==='asset'?['label','x','y','width','height']:el.kind==='text'?['text','x','y','font_size']:['label','x1','y1','x2','y2'];
    const names={label:'라벨',text:'텍스트',x:'가로 위치',y:'세로 위치',width:'너비',height:'높이',font_size:'글자 크기',x1:'시작 X',y1:'시작 Y',x2:'끝 X',y2:'끝 Y'};
    editor.innerHTML=`<form id="elementForm"><strong>${el.kind==='asset'?'클립아트':el.kind==='text'?'텍스트':'화살표'}</strong>${fields.map(k=>`<label>${names[k]}<input name="${k}" type="${typeof el[k]==='number'?'number':'text'}" step="any" value="${escape(el[k])}" maxlength="120"></label>`).join('')}<button class="secondary">적용</button>${el.kind==='asset'?'':'<button type="button" id="removeElement" class="plain">삭제</button>'}</form>`;
    $('#elementForm').onsubmit=async e=>{e.preventDefault();const patch={};for(const [k,v]of new FormData(e.target))patch[k]=typeof el[k]==='number'?Number(v):v;await changeElement(el,patch);};
    if($('#removeElement'))$('#removeElement').onclick=async()=>{const key=el.kind==='arrow'?'arrows':'texts';selected=null;await saveScene({[key]:scene[key].filter(o=>o.id!==el.id)});};
    controls();
  }
  $('#addText').onclick=async()=>{const id='text-'+Date.now();selected=id;await saveScene({texts:[...(scene.texts||[]),{id,x:100,y:130,text:'설명',font_size:24}]});};
  $('#addArrow').onclick=async()=>{const id='arrow-'+Date.now();selected=id;await saveScene({arrows:[...(scene.arrows||[]),{id,x1:500,y1:400,x2:750,y2:400,label:''}]});};

  return {async open(fromTray){
    visible=true;root.hidden=false;document.body.classList.add('studio-open');
    clearTimeout(timer);await connection();const projects=await projectList();
    if(fromTray&&!activeJob())await newProject();else if(!project&&projects.length)await loadProject(projects[0].id);
    renderProject();renderCanvas();timer=setTimeout(tick,1200);$('#studioPrompt').focus();
  }};
}
