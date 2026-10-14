import './desktop.js';
import { setupStudio } from './studio.js';
import { setupEditor } from './editor.js';
const $ = s => document.querySelector(s);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state = {q:'',topic:'all',format:'',license:'',scope:'related',tray:[],items:[],next:null,selected:null,file:null,dark:false,token:'',stats:null};
let searchController, searchTimer, detailSequence=0, toastTimer, sessionQueue=Promise.resolve();
async function api(path, body, options={}) {
  const response = await fetch(path,{...options, ...(body===undefined?{}:{method:'POST',headers:{'Content-Type':body instanceof Blob?'application/zip':'application/json','X-Bioart-Token':state.token},body:body instanceof Blob?body:JSON.stringify(body)})});
  if (!response.ok) { let message=`요청 실패 (${response.status})`;try{message=(await response.json()).detail||message;}catch{}throw Error(typeof message==='string'?message:JSON.stringify(message)); }
  return response.json();
}
function toast(message){$('#toast').textContent=message;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,4500);}
function fail(error){console.error(error);toast(error.message);}
function save(){const snapshot={tray:[...state.tray],query:state.q,topic:state.topic,format:state.format,license:state.license,scope:state.scope};sessionQueue=sessionQueue.catch(()=>{}).then(()=>api('/api/session',snapshot)).catch(fail);}
function modal(title,html){$('#modalTitle').textContent=title;$('#modalBody').innerHTML=html;if(!$('#modal').open)$('#modal').showModal();}
$('#modalClose').onclick=()=>$('#modal').close();
$('#modal').addEventListener('click',e=>{if(e.target===$('#modal')){const r=e.target.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)e.target.close();}});
function icon(topic){return {all:'▦',respiratory:'♧',immune:'❋',cells:'◉',anatomy:'♡',molecules:'⌬',laboratory:'⚗',organisms:'♧',elements:'↗'}[topic]||'◇';}
function renderTopics(){
 $('#topics').innerHTML=state.stats.topics.map(t=>`<button class="topic ${state.topic===t.id?'active':''}" data-topic="${esc(t.id)}"><span class="topic-icon">${icon(t.id)}</span>${esc(t.label)}<span class="count">${t.count}</span></button>`).join('');
 $('#topics').querySelectorAll('button').forEach(b=>b.onclick=()=>{state.topic=b.dataset.topic;state.q='';$('#search').value='';runSearch();});
}
function query(q){state.q=q;state.topic='all';$('#search').value=q;runSearch();}
document.querySelectorAll('[data-query]').forEach(b=>b.onclick=()=>query(b.dataset.query));
$('#search').addEventListener('input',e=>{state.q=e.target.value;clearTimeout(searchTimer);searchTimer=setTimeout(runSearch,200);});
$('#search').addEventListener('keydown',e=>{if(e.key==='Enter'){clearTimeout(searchTimer);runSearch();}});
$('#clearSearch').onclick=()=>query('');
for(const key of ['format','license','scope'])$(`#${key}`).onchange=e=>{state[key]=e.target.value;runSearch();};
$('#resetFilters').onclick=()=>{state.format='';state.license='';state.scope='related';for(const k of ['format','license','scope'])$(`#${k}`).value=state[k];runSearch();};
async function runSearch(append=false){
 searchController?.abort();searchController=new AbortController();const controller=searchController;
 $('#clearSearch').hidden=!state.q;renderTopics();
 const topic=state.stats.topics.find(t=>t.id===state.topic)?.label||'전체 그림';
 $('#heading').firstChild.textContent=state.q?`“${state.q}” `:topic+' ';
 $('#breadcrumb').textContent=state.q?'검색 결과':topic;$('#eyebrow').textContent=state.q?'DISCOVER CONNECTIONS':'THE LOCAL COLLECTION';
 if(!append){$('#results').innerHTML='<div class="loading">그림을 찾고 있습니다…</div>';$('#resultCount').textContent='';$('#library').scrollTop=0;}
 $('#loadMore').hidden=true;
 try{
  const params=new URLSearchParams({q:state.q,topic:state.topic,format:state.format,license:state.license,scope:state.scope,cursor:append?state.next:0,limit:60});
  const result=await api('/api/search?'+params,undefined,{signal:controller.signal});
  if(controller!==searchController)return;
  state.items=append?[...state.items,...result.items]:result.items;state.next=result.next_cursor;
  $('#resultCount').textContent=result.total.toLocaleString();
  $('#queryContext').innerHTML=result.resolved_concepts.length?`<div class="context-line">찾은 개념 ${result.resolved_concepts.map(c=>`<span class="concept-pill">${esc(c.label)}</span>`).join('')} <span>· ${state.scope==='related'?'관련 구조 1단계 포함':'직접 일치'}</span></div>`:'';
  renderResults();$('#loadMore').hidden=state.next===null;save();
 }catch(e){if(e.name!=='AbortError'){$('#results').innerHTML=`<div class="empty-results"><h2>라이브러리를 불러오지 못했습니다</h2><p>${esc(e.message)}</p><button class="secondary" id="retrySearch">다시 시도</button></div>`;$('#retrySearch').onclick=()=>runSearch();}}
}
$('#loadMore').onclick=()=>runSearch(true);
function card(a){const added=state.tray.includes(a.preview_file_id);return `<article class="art-card ${state.selected?.id===a.id?'selected':''}" data-id="${a.id}"><button class="quick-add ${added?'added':''}" data-add="${a.preview_file_id}" aria-label="${esc(a.title)} ${added?'트레이에서 제거':'트레이에 추가'}">${added?'✓':'+'}</button><button class="art-button" data-open="${a.id}"><div class="art-image"><span class="art-format">${esc(a.formats.join(' / '))}</span><img src="${a.thumbnail}" alt="${esc(a.title)}" loading="lazy" decoding="async"></div><div class="art-title">${esc(a.title)}</div><div class="art-meta"><span>${a.file_count}개 파일 · 미검토</span><span>${esc(a.license)}</span></div>${state.q?`<div class="art-reason">${esc(a.reason)}</div>`:''}</button></article>`;}
function renderResults(){
 if(!state.items.length){$('#results').innerHTML=`<div class="empty-results"><span class="outline-art">⌕</span><h2>일치하는 그림이 없습니다</h2><p>더 넓은 개념으로 검색하거나 필터를 해제해 보세요.<br>현재 카탈로그에 없는 그림은 결과에 표시하지 않습니다.</p><button id="emptyReset" class="secondary">전체 라이브러리 보기</button></div>`;$('#emptyReset').onclick=()=>{state.format='';state.license='';$('#format').value='';$('#license').value='';query('');};return;}
 const direct=state.items.filter(a=>a.match_type!=='relation'), related=state.items.filter(a=>a.match_type==='relation');
 $('#results').innerHTML=(direct.length?`${related.length?'<div class="section-label">직접 일치 <span>제목·명칭·원본 키워드</span></div>':''}<div class="gallery">${direct.map(card).join('')}</div>`:'')+(related.length?`<div class="section-label">관련 구조 <span>부분–전체 관계 · 출처 포함</span></div><div class="gallery">${related.map(card).join('')}</div>`:'');
 $('#results').querySelectorAll('[data-open]').forEach(b=>b.onclick=()=>selectAsset(b.dataset.open,state.items.find(a=>a.id===b.dataset.open)?.preview_file_id));
 $('#results').querySelectorAll('[data-add]').forEach(b=>b.onclick=()=>toggleTray(b.dataset.add));
}
async function selectAsset(aid,fid){
 const seq=++detailSequence;
 try{const a=await api('/api/assets/'+aid);if(seq!==detailSequence)return;state.selected=a;state.file=a.files.find(f=>f.id===fid&&f.status==='valid')||a.files.find(f=>f.status==='valid');renderInspector();renderResults();
 const related=await api('/api/related/'+aid);if(seq===detailSequence)renderRelated(related);
 }catch(e){fail(e);}
}
function renderInspector(){
 const a=state.selected,f=state.file;if(!a||!f)return;
 const meta=a.source_status==='verified'?a.metadata:{};const size=f.bytes>1048576?(f.bytes/1048576).toFixed(1)+' MB':Math.round(f.bytes/1024)+' KB';
 $('#inspector').innerHTML=`<div class="inspector-content"><div class="inspector-top">BIOART-${String(a.id).padStart(6,'0')}<button id="closeInspector" class="icon-button" aria-label="상세 닫기">×</button></div><div class="preview-stage ${state.dark?'dark':''}" id="previewStage"><img src="/api/preview/${f.id}" alt="${esc(a.title)}"></div><div class="preview-actions"><button id="backgroundButton">◐ ${state.dark?'밝은':'어두운'} 배경</button><button id="zoomButton">확대 보기 ⤢</button></div><h2>${esc(a.title)}</h2><div class="subline"><span>${esc(a.license)}</span><span>·</span><span class="tag">이미지 미검토</span></div><div class="inspection-note">${a.source_status==='verified'?'원본 ID·제목 확인됨. 그림의 세부 내용은 아직 검토하지 않았습니다.':a.source_status==='identity_conflict'?'원본 페이지의 ID 또는 제목이 다릅니다. 메타데이터를 자동 연결하지 않았습니다.':'파일 제목으로 탐색할 수 있습니다. 원본 상세 정보는 수집 대기 또는 확인 필요 상태입니다.'}</div><div class="inspector-section"><div class="section-heading">표현과 파일 <small>${a.file_count}개 · 포맷 대응 미확정</small></div><div class="variants">${a.files.filter(v=>v.status==='valid').map(v=>`<button class="variant ${v.id===f.id?'active':''}" data-file="${v.id}" aria-label="${v.format} 파일 ${v.id}"><img src="/api/preview/${v.id}" loading="lazy" alt=""><small>${v.format} · ${v.id}</small></button>`).join('')}</div><div class="file-info">선택 파일 ${f.id} · ${f.format} · ${size}<br>${f.image?.width||'?'} × ${f.image?.height||'?'}${f.format==='SVG'?' (미리보기)':''} · SHA-256 확인됨${a.files.some(v=>v.status!=='valid')?'<br>사용할 수 없는 파일은 선택 목록에서 제외했습니다.':''}</div><button class="primary" id="addSelected">${state.tray.includes(f.id)?'✓ 트레이에서 제거':'+ 제작 트레이에 추가'}</button></div><div id="relatedSection"></div><div class="inspector-section"><div class="section-heading">원본 정보 <small>${a.source_status==='verified'?'출처 메타데이터':'미확인'}</small></div><div class="description">${esc(meta.description||'확인된 원본 설명이 없습니다.')}</div><dl class="source-list"><dt>제작자</dt><dd>${esc(meta.creator||'미확인')}</dd><dt>Credit</dt><dd>${esc(meta.credit||'미확인')}</dd><dt>라이선스</dt><dd>${esc(a.license)}${meta.license_url?` <a href="${esc(meta.license_url)}" target="_blank" rel="noreferrer">↗</a>`:' · 상세 미확인'}</dd><dt>키워드</dt><dd>${esc(meta.keywords||'미확인')}</dd></dl><a class="source-link" href="${esc(a.source_url)}" target="_blank" rel="noreferrer">NIH BioArt Source에서 보기 ↗</a></div></div>`;
 $('#closeInspector').onclick=closeInspector;
 $('#backgroundButton').onclick=()=>{state.dark=!state.dark;$('#previewStage').classList.toggle('dark',state.dark);$('#backgroundButton').textContent=`◐ ${state.dark?'밝은':'어두운'} 배경`;};
 $('#zoomButton').onclick=()=>modal(a.title,`<div style="background:${state.dark?'#273c38':'#f2f4ed'};border-radius:7px;padding:20px"><img class="modal-image" src="/api/preview/${f.id}?size=1200" alt="${esc(a.title)}"></div><p class="relation-evidence">파일 ${f.id} · ${f.format} · 이미지 내용 미검토</p>`);
 $('#addSelected').onclick=()=>toggleTray(f.id);
 $('#inspector').querySelectorAll('[data-file]').forEach(b=>b.onclick=()=>{state.file=a.files.find(v=>v.id===b.dataset.file);renderInspector();api('/api/related/'+a.id).then(renderRelated).catch(fail);});
}
function closeInspector(){++detailSequence;state.selected=null;state.file=null;$('#inspector').innerHTML='<div class="inspector-empty"><span class="outline-art">✳</span><h2>그림을 선택하세요</h2><p>표현을 비교하고 제작 트레이에 모아두세요.</p></div>';renderResults();}
function renderRelated(result){if(!$('#relatedSection'))return;$('#relatedSection').innerHTML=result.groups.map(g=>`<div class="inspector-section"><div class="section-heading">${esc(g.label)}</div><div class="related-list">${g.items.map(a=>`<button class="related-item" data-related="${a.id}"><img src="${a.thumbnail}" alt=""><span>${esc(a.title)}</span>↗</button>`).join('')}</div><p class="relation-evidence">${esc(g.relation.label)} <a href="${esc(g.relation.evidence_ref)}" target="_blank" rel="noreferrer">근거 ↗</a><br>관계 출처와 개별 그림의 묘사 여부는 별도입니다.</p></div>`).join('');$('#relatedSection').querySelectorAll('[data-related]').forEach(b=>b.onclick=()=>selectAsset(b.dataset.related));}
function toggleTray(fid){if(state.tray.includes(fid))state.tray=state.tray.filter(id=>id!==fid);else {if(state.tray.length>=100){toast('트레이는 최대 100개 파일을 담을 수 있습니다.');return;}state.tray.push(fid);}renderTray();renderResults();if(state.file)$('#addSelected').textContent=state.tray.includes(state.file.id)?'✓ 트레이에서 제거':'+ 제작 트레이에 추가';save();}
function renderTray(){
 $('#trayCount').textContent=state.tray.length;
 $('#trayItems').innerHTML=state.tray.length?state.tray.map(id=>`<div class="tray-item"><button data-tray="${id}" aria-label="파일 ${id} 상세"><img src="/api/preview/${id}" alt="파일 ${id}"></button><button class="tray-remove" data-remove="${id}" aria-label="파일 ${id} 제거">×</button></div>`).join(''):'<span class="tray-placeholder">그림을 선택하고 + 버튼으로 추가하세요</span>';
 $('#trayItems').querySelectorAll('[data-remove]').forEach(b=>b.onclick=()=>toggleTray(b.dataset.remove));
 $('#trayItems').querySelectorAll('[data-tray]').forEach(b=>b.onclick=async()=>{try{const f=await api('/api/files/'+b.dataset.tray);selectAsset(f.artwork_id,f.id);}catch(e){fail(e);}});
 $('#exportButton').disabled=!state.tray.length;$('#compareButton').disabled=!state.tray.length||state.tray.length>24;$('#sceneButton').disabled=!state.tray.length||state.tray.length>8;
 $('#sceneButton').title='선택한 1–8개 파일로 도해 만들기';$('#compareButton').title='최대 24개 파일 비교';
}
async function busy(button,action){const text=button.textContent;button.disabled=true;button.textContent='처리 중…';try{await action();}catch(e){fail(e);}finally{button.textContent=text;button.disabled=false;}}
function showExport(result){modal('내보내기 완료',`<div class="modal-copy"><p>${result.portable?`휴대용 프로젝트 ZIP을 저장했습니다. 원본 자료 ${result.resources}개 · 생성 이미지 ${result.images}개를 포함합니다.`:"파일과 출처 목록을 함께 저장했습니다."}</p>${result.dimensions?`<p><strong>${esc(result.dimensions.widthMm)} × ${result.dimensions.heightMm.toFixed(2)} mm · ${result.dimensions.dpi} DPI</strong><br>${result.dimensions.pixelWidth.toLocaleString()} × ${result.dimensions.pixelHeight.toLocaleString()} px · sRGB<br>${Object.keys(result.quality).map(f=>f.toUpperCase()).join(" · ")} · 크기·DPI·글꼴 검사 완료</p>`:""}<code>${esc(result.path)}</code><p>원본 파일 ID, 체크섬, 출처와 확인 가능한 라이선스 정보가 포함됩니다.</p>${result.warnings?.length?`<p class="error-text">${result.portable?esc(result.warnings.join(" · ")):`프리플라이트 경고 ${result.warnings.length}개 · 상세 내용은 preflight.txt에 기록했습니다.`}</p>`:''}<div class="dialog-actions"><button class="secondary" id="revealExport">Finder에서 보기</button><a class="download-link" href="${result.download_url}">ZIP 다운로드 ↗</a></div></div>`);$('#revealExport').onclick=()=>{if(window.bioartDesktop)window.bioartDesktop.reveal(result.path);else if(window.webkit?.messageHandlers?.native)window.webkit.messageHandlers.native.postMessage({action:'reveal',path:result.path});else{navigator.clipboard?.writeText(result.path).then(()=>toast('저장 경로를 복사했습니다.')).catch(()=>toast(result.path));}};}
$('#exportButton').onclick=()=>busy($('#exportButton'),async()=>showExport(await api('/api/export',{file_ids:state.tray})));
$('#compareButton').onclick=()=>busy($('#compareButton'),async()=>{const response=await fetch('/api/compare',{method:'POST',headers:{'Content-Type':'application/json','X-Bioart-Token':state.token},body:JSON.stringify({file_ids:state.tray})});if(!response.ok)throw Error((await response.json()).detail);const url=URL.createObjectURL(await response.blob());modal('선택한 그림 비교',`<img class="modal-image" src="${url}" alt="번호와 파일 ID가 표시된 비교판">`);$('#modal').addEventListener('close',()=>URL.revokeObjectURL(url),{once:true});});
const studio = setupStudio({api, toast, fail, showExport, getTray:()=>[...state.tray]});
const editor = setupEditor({api, toast, fail, showExport, getTray:()=>[...state.tray]});
$('#editorButton').onclick=()=>editor.open().catch(fail);
$('#editTrayButton').onclick=()=>editor.open([...state.tray]).catch(fail);
$('#sceneButton').onclick=()=>studio.open(true).catch(fail);
$('#studioButton').onclick=()=>studio.open(false).catch(fail);
$('#helpButton').onclick=()=>modal('BioArt Browser 사용 안내',`<div class="modal-copy"><p><strong>개념으로 찾고, 파일을 확인하고, 트레이에 모으세요.</strong></p><ol><li>한국어·영어 명칭을 검색하거나 왼쪽 주제를 선택하세요.</li><li>오른쪽 패널에서 표현을 비교하고 정확한 PNG 또는 SVG 파일을 선택하세요.</li><li>트레이에서 파일을 비교하고, 원본과 출처 목록을 내보내세요.</li><li>제작실에서 Codex 구독을 연결해 원본 조합 또는 AI 이미지를 만들고, 대화와 캔버스로 수정하세요.</li></ol><p>현재 검색은 제목·원본 키워드·한영 별칭을 사용합니다. 자연어 의미 검색과 전체 이미지 내용 주석은 아직 완료되지 않았습니다.</p><p><kbd>⌘ K</kbd> 검색 · <kbd>Esc</kbd> 상세 닫기 · <kbd>Tab</kbd> 이동 · <kbd>Enter</kbd> 선택</p></div>`);
$('#statusButton').onclick=async()=>{try{state.stats=await api('/api/stats');const s=state.stats;modal('카탈로그 상태',`<div class="modal-copy"><table><tr><td>작품</td><td>${s.artworks.toLocaleString()}</td></tr><tr><td>유효 파일</td><td>${s.valid_files.toLocaleString()} / ${s.files.toLocaleString()}</td></tr><tr><td>파일 상태</td><td>${esc(JSON.stringify(s.statuses))}</td></tr><tr><td>원본 정보</td><td>${esc(JSON.stringify(s.metadata))}</td></tr><tr><td>시각 주석</td><td>검토 대기 · 모델 실행 전</td></tr><tr><td>카탈로그 버전</td><td>${esc(s.catalog_version)}</td></tr></table><p>자료 폴더 ${s.source_available?'연결됨':'연결 필요'}</p><code>${esc(s.source_root)}</code><div class="modal-form"><input id="sourcePath" aria-label="자료 폴더 경로" value="${esc(s.source_root)}"><button id="reconnectRoot" class="secondary">다시 연결</button></div><p class="relation-evidence">다시 연결할 때 모든 유효 파일의 ID·경로·체크섬을 확인합니다. 원본은 수정하지 않습니다.</p></div>`);$('#reconnectRoot').onclick=()=>busy($('#reconnectRoot'),async()=>{await api('/api/settings/source',{path:$('#sourcePath').value});toast('자료 폴더의 모든 파일을 확인하고 연결했습니다.');$('#modal').close();});}catch(e){fail(e);}};
document.addEventListener('keydown',e=>{if(document.body.classList.contains('editor-open'))return;if((e.metaKey||e.ctrlKey)&&e.key==='k'){e.preventDefault();$('#search').focus();$('#search').select();}if(e.key==='Escape'&&!$('#modal').open&&!document.body.classList.contains('studio-open'))closeInspector();});
async function init(){try{const session=await api('/api/session');state.token=session.token;Object.assign(state,{tray:session.state.tray||[],q:session.state.query||'',topic:session.state.topic||'all',format:session.state.format||'',license:session.state.license||'',scope:session.state.scope||'related'});state.stats=await api('/api/stats');$('#catalogCount').textContent=`${state.stats.artworks.toLocaleString()} 작품 · ${state.stats.valid_files.toLocaleString()} 파일`;$('#search').value=state.q;for(const k of ['format','license','scope'])$(`#${k}`).value=state[k];renderTopics();renderTray();await runSearch();}catch(e){$('#results').innerHTML=`<div class="empty-results"><h2>초기 설정이 필요합니다</h2><p>${esc(e.message)}</p><p>프로젝트 폴더에서 <code>uv run bioart inventory</code>를 실행하세요.</p><button class="secondary" id="retryInit">다시 연결</button></div>`;$('#retryInit').onclick=init;}}
init();
