import { ActiveSelection, Canvas, Ellipse, FabricObject, Group, IText, Path, PencilBrush, Point, Rect, controlsUtils, util } from 'fabric';
import type { TSimplePathData } from 'fabric';
import { History, detachMissing, node, remap, style, uid, walk } from './model';
import type { API, AssetData, FigureDocument, Node, Style } from './model';
import { ConnectorPath, allObjects, anchorPoint, connectionPath, editableSVG, fromNode, getAsset, objectTransform, serialize, toNode, updateConnections } from './adapter';
import { portableDialog } from './portable';
import { PublicationUI } from './publication';
import { ScienceUI, sciencePanel } from './science-ui';
import { generate, refreshInsets, scienceName } from './science';
import type { BrushId } from './science';
import { booleanPath, nearestSegment, simplify } from './geometry';

const esc=(v:unknown)=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]??c));
const label:Record<string,string>={rect:'사각형',ellipse:'타원',path:'경로',text:'텍스트',asset:'원본 그림',image:'AI 이미지',group:'그룹',connector:'연결선'};
type Tool='select'|'direct'|'hand'|'rect'|'ellipse'|'polygon'|'star'|'bracket'|'arc'|'line'|'arrow'|'pen'|'pencil'|'text'|'eyedropper';
interface Hooks {api:API;toast:(s:string)=>void;fail:(e:Error)=>void;showExport:(r:unknown)=>void;getTray:()=>string[]}
export function setupEditor(hooks:Hooks){return new Editor(hooks);}
class Editor {
 private publication:PublicationUI;private scienceUI:ScienceUI;private brush:BrushId|null=null;private insetEpoch=0;
 private root:HTMLElement;private canvas:Canvas;private document:FigureDocument|null=null;private history=new History('');
 private active=false;private restoring=false;private dirty=false;private saving:Promise<void>|null=null;private saveError=false;
 private tool:Tool='select';private clipboard:Node[]=[];private copiedStyle:Style|null=null;private color='#276a57';private fill='#b8d9c7';
 private drawStart:Point|null=null;private draft:FabricObject|null=null;private pan:Point|null=null;private penPoints:Point[]=[];private penDraft:Path|null=null;
 private directIndex=1;private snap=true;private grid=true;private searchSeq=0;private searchTimer:ReturnType<typeof setTimeout>|undefined;private guides:{x?:number;y?:number}={};
 constructor(private h:Hooks){
  this.root=document.createElement('section');this.root.id='diagramEditor';this.root.hidden=true;this.root.setAttribute('aria-label','자유 도해 편집기');document.body.append(this.root);
  this.root.innerHTML=`<header class="ed-header"><button data-action="back" title="라이브러리로 돌아가기">← 라이브러리</button><span class="ed-brand">BioArt <b>Studio</b></span><input id="edTitle" aria-label="도해 제목" maxlength="200"><span id="edSaved" role="status">문서 준비 중</span><div class="ed-header-right"><select id="edProjects" aria-label="저장한 도해"></select><button data-action="new">새 도해</button><button data-action="legacy">이전 도해</button><button data-action="portable">프로젝트 ZIP</button><button data-action="export" class="ed-primary">내보내기 ↗</button></div></header>
  <div class="ed-commandbar"><button data-action="undo" title="실행 취소 ⌘Z">↶ 실행 취소</button><button data-action="redo" title="다시 실행 ⇧⌘Z">↷</button><i></i><button data-action="duplicate">복제</button><button data-action="delete">삭제</button><button data-action="group">그룹</button><button data-action="ungroup">해제</button><i></i><select id="edAlign" aria-label="정렬"><option value="">정렬·간격</option><option value="left">왼쪽 정렬</option><option value="center">가로 중앙</option><option value="right">오른쪽 정렬</option><option value="top">위쪽 정렬</option><option value="middle">세로 중앙</option><option value="bottom">아래쪽 정렬</option><option value="horizontal">가로 간격 동일</option><option value="vertical">세로 간격 동일</option></select><label class="ed-check"><input id="edSnap" type="checkbox" checked>스냅</label><label class="ed-check"><input id="edGrid" type="checkbox" checked>격자</label><span class="ed-spacer"></span><button data-action="toggle-assets">자료 패널</button><button data-action="toggle-properties">속성 패널</button></div>
  <div class="ed-body"><nav class="ed-tools" aria-label="그리기 도구">${([['select','↖','선택 V'],['direct','◇','경로 점 편집 A'],['hand','✥','이동 H'],['rect','▭','사각형 R'],['ellipse','◯','타원 O'],['polygon','⬡','다각형'],['star','☆','별'],['bracket','[','괄호'],['arc','◠','호'],['line','╱','선 L'],['arrow','→','연결선 C'],['pen','⌁','펜 P'],['pencil','✎','자유곡선 B'],['text','T','텍스트 T'],['eyedropper','◉','색 가져오기 I']] as const).map(([id,glyph,name])=>`<button data-tool="${id}" title="${name}" aria-label="${name}">${glyph}</button>`).join('')}<div class="ed-tool-colors"><input id="edDefaultFill" type="color" value="#b8d9c7" aria-label="그리기 채움색"><input id="edDefaultStroke" type="color" value="#276a57" aria-label="그리기 선색"></div></nav>
  <aside class="ed-assets"><div class="ed-tabs"><button data-tab="assets" class="active">BioArt 자료</button><button data-tab="science">과학 제작</button><button data-tab="layers">레이어</button></div><section id="edAssetPanel"><input id="edSearch" placeholder="폐, 항체, neuron…" aria-label="편집기 자료 검색"><select id="edFormat" aria-label="편집기 자료 형식"><option value="">모든 형식</option><option>SVG</option><option>PNG</option></select><p class="ed-caption">클릭하거나 캔버스로 끌어 넣으세요.</p><div id="edSearchResults"></div></section><section id="edSciencePanel" hidden>${sciencePanel}</section><section id="edLayerPanel" hidden><p class="ed-caption">위쪽이 앞 레이어입니다.</p><div id="edLayers"></div><div class="ed-buttons"><button data-action="front">맨 앞으로</button><button data-action="backward">뒤로</button></div></section></aside>
  <main class="ed-main"><div id="edRecovery" hidden></div><div id="edCanvasArea"><canvas id="edCanvas" aria-label="과학 도해 캔버스"></canvas></div><footer class="ed-footer"><span id="edHint">빈 캔버스에서 시작하세요. 그림·도형·텍스트를 자유롭게 배치할 수 있습니다.</span><div><button data-action="zoom-out" aria-label="축소">−</button><span id="edZoom">100%</span><button data-action="zoom-in" aria-label="확대">+</button><button data-action="fit">화면에 맞춤</button></div></footer></main>
  <aside class="ed-properties"><div id="edProperties"></div></aside></div>
  <dialog id="edDialog"><div class="ed-dialog-head"><h2 id="edDialogTitle"></h2><button id="edDialogClose" aria-label="대화상자 닫기">×</button></div><div id="edDialogBody"></div></dialog>`;
  this.publication=new PublicationUI({api:this.h.api,showExport:this.h.showExport,snapshot:async()=>{await this.flush();if(!this.document)throw Error('도해를 먼저 여세요.');return structuredClone(this.document);},select:id=>{let o=allObjects(this.canvas).find(o=>o.bio?.id===id);if(o){while(o.group)o=o.group;this.canvas.setActiveObject(o);this.canvas.requestRenderAll();this.properties();}}},this.q('.ed-commandbar'));
  const el=this.q<HTMLCanvasElement>('#edCanvas');this.canvas=new Canvas(el,{preserveObjectStacking:true,selection:true,enableRetinaScaling:true,stopContextMenu:true,fireRightClick:false,backgroundColor:''});
  this.scienceUI=new ScienceUI({selected:()=>{const o=this.canvas.getActiveObject();return o&&!(o instanceof ActiveSelection)?toNode(o,true):null;},nodes:()=>serialize(this.canvas),put:(nodes,replace)=>this.putScience(nodes,replace),example:async(title,nodes)=>{await this.newDocument();if(!this.document)return;this.document.title=title;this.q<HTMLInputElement>('#edTitle').value=title;await this.putScience(nodes);this.canvas.discardActiveObject();this.properties();this.fit();},dialog:(title,body)=>{this.dialog(title,body);return this.q('#edDialogBody');},close:()=>this.q<HTMLDialogElement>('#edDialog').close(),error:e=>this.error(e),draw:id=>{this.setTool('pencil');this.brush=id;this.message('캔버스를 끌어 과학 브러시를 그리세요. 완성 후 설정을 다시 바꿀 수 있습니다.');}},this.q('#edSciencePanel'));
  this.bind();new ResizeObserver(()=>{if(this.active){this.resize();}}).observe(this.q('#edCanvasArea'));
 }
 private q<T extends HTMLElement=HTMLElement>(s:string):T{const el=this.root.querySelector<T>(s);if(!el)throw Error('Missing editor control '+s);return el;}
 private message(s:string){this.q('#edHint').textContent=s;}
 private error(e:unknown){this.h.fail(e instanceof Error?e:Error(String(e)));}
 private bind(){
  this.root.querySelectorAll<HTMLButtonElement>('[data-action]').forEach(b=>b.onclick=()=>{void this.action(b.dataset.action??'').catch(e=>this.error(e));});
  this.root.querySelectorAll<HTMLButtonElement>('[data-tool]').forEach(b=>b.onclick=()=>this.setTool(b.dataset.tool as Tool));
  this.root.querySelectorAll<HTMLButtonElement>('[data-tab]').forEach(b=>b.onclick=()=>this.tab(b.dataset.tab??'assets'));
  this.q<HTMLButtonElement>('#edDialogClose').onclick=()=>this.q<HTMLDialogElement>('#edDialog').close();
  this.q<HTMLInputElement>('#edTitle').oninput=()=>{if(this.document){this.document.title=this.q<HTMLInputElement>('#edTitle').value;this.commit();}};
  this.q<HTMLSelectElement>('#edProjects').onchange=()=>{void this.switchDocument(this.q<HTMLSelectElement>('#edProjects').value).catch(e=>this.error(e));};
  this.q<HTMLInputElement>('#edSearch').oninput=()=>{clearTimeout(this.searchTimer);this.searchTimer=setTimeout(()=>void this.search().catch(e=>this.error(e)),200);};
  this.q<HTMLSelectElement>('#edFormat').onchange=()=>void this.search().catch(e=>this.error(e));
  this.q<HTMLSelectElement>('#edAlign').onchange=()=>{this.align(this.q<HTMLSelectElement>('#edAlign').value);this.q<HTMLSelectElement>('#edAlign').value='';};
  this.q<HTMLInputElement>('#edGrid').onchange=()=>{this.grid=this.q<HTMLInputElement>('#edGrid').checked;this.canvas.requestRenderAll();};
  this.q<HTMLInputElement>('#edSnap').onchange=()=>this.snap=this.q<HTMLInputElement>('#edSnap').checked;
  this.q<HTMLInputElement>('#edDefaultFill').oninput=()=>this.fill=this.q<HTMLInputElement>('#edDefaultFill').value;
  this.q<HTMLInputElement>('#edDefaultStroke').oninput=()=>{this.color=this.q<HTMLInputElement>('#edDefaultStroke').value;if(this.canvas.freeDrawingBrush)this.canvas.freeDrawingBrush.color=this.color;};
  this.canvas.on('before:render',()=>this.drawBoard());
  this.canvas.on('after:render',()=>this.drawGuides());
  for(const event of ['selection:created','selection:updated','selection:cleared'] as const)this.canvas.on(event,()=>{if(!this.restoring){this.properties();this.layers();}});
  this.canvas.on('object:modified',()=>{this.guides={};updateConnections(this.canvas);this.commit();});
  this.canvas.on('object:moving',e=>{if(this.snap&&!e.target.bio?.link)this.snapping(e.target);updateConnections(this.canvas);});
  this.canvas.on('object:scaling',()=>updateConnections(this.canvas));this.canvas.on('object:rotating',()=>updateConnections(this.canvas));
  this.canvas.on('text:changed',()=>this.commit(false));
  this.canvas.on('text:editing:exited',()=>this.commit());
  this.canvas.on('path:created',e=>{try{e.path.bio=node('path',{name:'자유곡선'});if(this.brush){const original=toNode(e.path),n=generate({type:'brush',version:1,id:this.brush,params:{width:360,height:140,spacing:18,thickness:36,count:18,seed:17,color:this.color,accent:'#d99b73'},path:original.path});n.transform=original.transform;void this.putScience([n],original.id).catch(x=>{this.error(x);this.commit();});}else this.commit();}catch(error){this.error(error);this.commit();}});
  this.canvas.on('mouse:down',e=>this.pointerDown(e.scenePoint,e.viewportPoint,e.target,e.e));
  this.canvas.on('mouse:move',e=>this.pointerMove(e.scenePoint,e.viewportPoint));
  this.canvas.on('mouse:up',e=>this.pointerUp(e.scenePoint,e.target));
  this.canvas.on('mouse:dblclick',e=>{if(this.tool==='pen')this.finishPen(false);else if(this.tool==='direct'&&e.target instanceof Path){this.directIndex=nearestSegment(e.target,e.scenePoint);this.properties();}});
  this.canvas.on('mouse:wheel',e=>{e.e.preventDefault();e.e.stopPropagation();const factor=Math.pow(.999,e.e.deltaY);this.canvas.zoomToPoint(e.viewportPoint,Math.min(5,Math.max(.08,this.canvas.getZoom()*factor)));this.zoomLabel();});
  this.canvas.upperCanvasEl.addEventListener('pointercancel',()=>{if(this.draft)this.canvas.remove(this.draft);this.draft=null;this.drawStart=null;this.pan=null;void this.reloadCurrentSnapshot();});
  const area=this.q('#edCanvasArea');area.ondragover=e=>e.preventDefault();area.ondrop=e=>{e.preventDefault();const fid=e.dataTransfer?.getData('text/x-bioart-id'),aid=e.dataTransfer?.getData('text/x-bioart-asset');if(fid){const p=this.canvas.getScenePoint(e);void (aid?this.resolveAsset(aid,fid,this.q<HTMLSelectElement>('#edFormat').value,p):this.addAsset(fid,p)).catch(x=>this.error(x));}};
  document.addEventListener('keydown',e=>this.keys(e),true);
  window.addEventListener('beforeunload',e=>{if(this.dirty||this.saving){e.preventDefault();e.returnValue='';}});
  document.addEventListener('visibilitychange',()=>{if(document.hidden&&this.dirty)void this.persist();});
 }
 async open(fileIds?:string[]){
  this.active=true;this.root.hidden=false;document.body.classList.add('editor-open');this.resize();
  if(fileIds){await this.newDocument(fileIds);}else if(!this.document){const docs=await this.h.api<FigureDocument[]>('/api/documents');if(docs[0])await this.load(docs[0].id);else await this.newDocument();}
  await this.projectList();await this.search();this.fit();this.setTool('select');
 }
 private async newDocument(fileIds:string[]=[]){await this.flush();const d=await this.h.api<FigureDocument>('/api/documents',{file_ids:fileIds});await this.accept(d);await this.projectList();}
 private async switchDocument(id:string){if(!id||id===this.document?.id)return;try{await this.flush();await this.load(id);}catch(e){if(this.document)this.q<HTMLSelectElement>('#edProjects').value=this.document.id;throw e;}}
 private async load(id:string){const d=await this.h.api<FigureDocument>('/api/documents/'+id);await this.accept(d);const recovery=await this.h.api<{document:FigureDocument;baseRevision:number}|null>('/api/documents/'+id+'/recovery');if(recovery){this.dialog('저장되지 않은 변경 사항',`<p>이 문서의 복구본이 있습니다. 현재 문서와 별도로 복구할 수 있습니다.</p><button id="edRecover" class="ed-primary">복구본을 새 도해로 열기</button>`);this.q('#edRecover').onclick=()=>void this.copyDocument(recovery.document).then(()=>this.q<HTMLDialogElement>('#edDialog').close()).catch(e=>this.error(e));}}
 private async accept(d:FigureDocument){this.document=d;this.dirty=false;this.saveError=false;await this.renderDocument();this.history=new History(this.snapshot());this.q<HTMLInputElement>('#edTitle').value=d.title;this.status('모든 변경 사항 저장됨');this.fit();this.properties();this.layers();}
 private async renderDocument(){
  if(!this.document)return;this.restoring=true;this.canvas.discardActiveObject();this.canvas.remove(...this.canvas.getObjects());
  try{const objects=await Promise.all(this.document.nodes.map(n=>fromNode(n,this.h.api)));this.canvas.add(...objects);updateConnections(this.canvas);}finally{this.restoring=false;this.canvas.requestRenderAll();}
 }
 private snapshot(){return JSON.stringify({title:this.document?.title,artboard:this.document?.artboard,nodes:this.document?.nodes});}
 private commit(refresh=true){
  if(this.restoring||!this.document)return;
  updateConnections(this.canvas);this.document.nodes=serialize(this.canvas);detachMissing(this.document.nodes);
  const changed=refreshInsets(this.document.nodes);if(changed.length)void this.renderInsets(changed);
  if(!this.history.push(this.snapshot()))return;
  this.dirty=true;this.status('저장 중…');if(refresh){this.properties();this.layers();}this.canvas.requestRenderAll();void this.persist();
 }
 private status(text:string){this.q('#edSaved').textContent=text;this.q('#edSaved').classList.toggle('error',this.saveError);this.root.querySelector<HTMLButtonElement>('[data-action="undo"]')!.disabled=!this.history.canUndo;this.root.querySelector<HTMLButtonElement>('[data-action="redo"]')!.disabled=!this.history.canRedo;}
 private persist():Promise<void>{
  if(this.saving)return this.saving;
  this.saving=(async()=>{while(this.dirty&&this.document&&!this.saveError){
   const snapshot=structuredClone(this.document);this.dirty=false;
   try{const saved=await this.h.api<FigureDocument>('/api/documents/'+snapshot.id,{document:snapshot,baseRevision:snapshot.revision,operationId:crypto.randomUUID()});
    this.document.revision=saved.revision;this.document.updatedAt=saved.updatedAt;
    const option=this.q<HTMLSelectElement>('#edProjects').selectedOptions[0];if(option?.value===saved.id)option.textContent=saved.title;
    if(!this.dirty)this.status('모든 변경 사항 저장됨');
   }catch(e){this.dirty=true;this.saveError=true;this.status('저장 실패 · 편집 내용 유지됨');this.q('#edRecovery').hidden=false;this.q('#edRecovery').innerHTML=`<span>${esc(e instanceof Error?e.message:e)}</span><button id="edRetrySave">재시도</button><button id="edSaveCopy">새 사본 저장</button>`;this.q('#edRetrySave').onclick=()=>{this.saveError=false;void this.persist();};this.q('#edSaveCopy').onclick=()=>{if(this.document)void this.copyDocument(this.document).catch(x=>this.error(x));};}
  }})().finally(()=>{this.saving=null;if(!this.dirty)this.q('#edRecovery').hidden=true;});return this.saving;
 }
 private async flush(){await this.saving;if(this.dirty){await this.persist();if(this.dirty)throw Error('저장되지 않은 변경이 있습니다. 재시도하거나 새 사본으로 저장하세요.');}}
 private async copyDocument(original:FigureDocument){const d=await this.h.api<FigureDocument>('/api/documents',{title:original.title+' · 사본'});d.nodes=structuredClone(original.nodes);d.artboard=structuredClone(original.artboard);const saved=await this.h.api<FigureDocument>('/api/documents/'+d.id,{document:d,baseRevision:d.revision,operationId:crypto.randomUUID()});await this.accept(saved);await this.projectList();this.q('#edRecovery').hidden=true;}
 private async projectList(){const docs=await this.h.api<FigureDocument[]>('/api/documents');this.q('#edProjects').innerHTML=docs.map(d=>`<option value="${d.id}">${esc(d.title)}</option>`).join('');if(this.document)this.q<HTMLSelectElement>('#edProjects').value=this.document.id;}
 private resize(){const r=this.q('#edCanvasArea').getBoundingClientRect();this.canvas.setDimensions({width:Math.max(100,r.width),height:Math.max(100,r.height)});}
 private fit(){if(!this.document)return;this.resize();const a=this.document.artboard,z=Math.min((this.canvas.width-80)/a.width,(this.canvas.height-80)/a.height);this.canvas.setViewportTransform([z,0,0,z,(this.canvas.width-a.width*z)/2,(this.canvas.height-a.height*z)/2]);this.zoomLabel();}
 private zoomLabel(){this.q('#edZoom').textContent=Math.round(this.canvas.getZoom()*100)+'%';this.canvas.requestRenderAll();}
 private drawBoard(){
  if(!this.document)return;const ctx=this.canvas.getContext(),v=this.canvas.viewportTransform,a=this.document.artboard;
  // Fabric fires before:render after clearing and before objects, so draw the artboard here.
  ctx.save();ctx.transform(...v);ctx.shadowColor='#23392b20';ctx.shadowBlur=20;ctx.fillStyle=a.background;ctx.fillRect(0,0,a.width,a.height);ctx.shadowBlur=0;
  if(this.grid&&this.canvas.getZoom()>.2){ctx.fillStyle='#276a5726';for(let x=0;x<a.width;x+=20)for(let y=0;y<a.height;y+=20)ctx.fillRect(x,y,1/this.canvas.getZoom(),1/this.canvas.getZoom());}
  ctx.strokeStyle='#bfc8bd';ctx.lineWidth=1/this.canvas.getZoom();ctx.strokeRect(0,0,a.width,a.height);ctx.restore();
 }
 private drawGuides(){const ctx=this.canvas.getContext(),v=this.canvas.viewportTransform;ctx.save();ctx.transform(...v);ctx.strokeStyle='#d18b40';ctx.lineWidth=1/this.canvas.getZoom();ctx.beginPath();if(this.guides.x!==undefined){ctx.moveTo(this.guides.x,-10000);ctx.lineTo(this.guides.x,10000);}if(this.guides.y!==undefined){ctx.moveTo(-10000,this.guides.y);ctx.lineTo(10000,this.guides.y);}ctx.stroke();ctx.restore();}
 private snapping(o:FabricObject){
  const threshold=7/this.canvas.getZoom(),center=o.getCenterPoint(),a=this.document?.artboard;if(!a)return;
  const xs=[0,a.width/2,a.width],ys=[0,a.height/2,a.height];
  for(const other of this.canvas.getObjects())if(other!==o&&!other.helper&&!this.canvas.getActiveObjects().includes(other)){const b=other.getBoundingRect();xs.push(b.left,b.left+b.width/2,b.left+b.width);ys.push(b.top,b.top+b.height/2,b.top+b.height);}
  const box=o.getBoundingRect(),xOffsets=[-box.width/2,0,box.width/2],yOffsets=[-box.height/2,0,box.height/2];this.guides={};
  const best=(pos:number,offsets:number[],targets:number[])=>{let delta=Infinity,target=0;for(const offset of offsets)for(const t of targets){const d=t-pos-offset;if(Math.abs(d)<Math.abs(delta)){delta=d;target=t;}}return {delta,target};};
  const x=best(center.x,xOffsets,xs),y=best(center.y,yOffsets,ys);
  if(Math.abs(x.delta)<threshold){o.left+=x.delta;this.guides.x=x.target;}else if(this.grid)o.left=Math.round(o.left/10)*10;
  if(Math.abs(y.delta)<threshold){o.top+=y.delta;this.guides.y=y.target;}else if(this.grid)o.top=Math.round(o.top/10)*10;
 }
 private setTool(tool:Tool){this.brush=null;
  this.finishPen(false);this.tool=tool;this.canvas.isDrawingMode=tool==='pencil';this.canvas.selection=tool==='select';this.canvas.skipTargetFind=!['select','direct','eyedropper','arrow'].includes(tool);this.canvas.defaultCursor=tool==='hand'?'grab':tool==='select'?'default':'crosshair';
  if(tool==='pencil'){const brush=new PencilBrush(this.canvas);brush.width=3;brush.color=this.color;this.canvas.freeDrawingBrush=brush;}
  for(const o of allObjects(this.canvas)){o.selectable=(tool==='select'||tool==='direct')&&!o.bio?.locked;o.evented=!o.bio?.locked;if(o instanceof Path)o.controls=tool==='direct'?controlsUtils.createPathControls(o):controlsUtils.createObjectDefaultControls();}
  this.root.querySelectorAll<HTMLButtonElement>('[data-tool]').forEach(b=>{const active=b.dataset.tool===tool;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));});
  this.message(tool==='pen'?'클릭해 점을 추가하세요. Enter: 완성 · Shift+Enter: 닫힌 경로 · Esc: 취소':tool==='direct'?'경로를 선택해 점과 곡선 핸들을 끄세요. 더블클릭으로 편집할 점을 지정할 수 있습니다.':tool==='arrow'?'그림의 가장자리에서 다른 그림까지 끌면 이동을 따라가는 연결선이 됩니다.':'Shift: 다중 선택 · ⌘D: 복제 · Space: 화면 이동 · 휠: 확대/축소');this.properties();this.canvas.requestRenderAll();
 }
 private pointerDown(p:Point,screen:Point,target:FabricObject|undefined,event:Event){
  if(this.tool==='hand'||('button'in event&&event.button===1)){this.pan=screen;return;}
  if(this.tool==='eyedropper'){if(target&&typeof target.fill==='string'){this.fill=target.fill;this.q<HTMLInputElement>('#edDefaultFill').value=this.fill;this.setTool('select');}return;}
  if(this.tool==='direct'&&target instanceof Path){this.directIndex=nearestSegment(target,p);return;}
  if(this.tool==='pen'){this.penPoints.push(p);this.updatePen();return;}
  if(this.tool==='text'){const text=new IText('텍스트',{left:p.x,top:p.y,fontSize:28,fontFamily:'Helvetica Neue',fill:this.color,strokeWidth:0});text.bio=node('text',{name:'텍스트'});this.canvas.add(text);this.setTool('select');this.canvas.setActiveObject(text);text.enterEditing();text.selectAll();this.commit();return;}
  if(!['rect','ellipse','line','arrow','polygon','star','bracket','arc'].includes(this.tool))return;
  this.canvas.discardActiveObject();this.drawStart=p;
  const opt={left:p.x,top:p.y,fill:this.fill,stroke:this.color,strokeWidth:2,selectable:false,evented:false};
  if(this.tool==='rect')this.draft=new Rect({...opt,width:1,height:1});
  else if(this.tool==='ellipse')this.draft=new Ellipse({...opt,rx:1,ry:1});
  else this.draft=this.tool==='arrow'?new ConnectorPath(`M ${p.x} ${p.y} L ${p.x+1} ${p.y}`,{...opt,fill:null}):new Path(`M ${p.x} ${p.y} L ${p.x+1} ${p.y}`,{...opt,fill:['line','bracket','arc'].includes(this.tool)?null:this.fill});
  const kind=this.tool==='arrow'?'connector':this.tool==='rect'?'rect':this.tool==='ellipse'?'ellipse':'path';
  this.draft.bio=node(kind,{name:label[kind]??'도형',link:kind==='connector'?{start:this.closestAnchor(target,p),end:null,mode:'straight',startHead:'none',endHead:'arrow'}:null});this.canvas.add(this.draft);
 }
 private closestAnchor(target:FabricObject|undefined,p:Point){if(!target?.bio||target.bio.kind==='connector'||target.helper)return null;const local=util.transformPoint(p,util.invertTransform(target.calcTransformMatrix()));const u=local.x/Math.max(1,target.width)+.5,v=local.y/Math.max(1,target.height)+.5;const options=[{x:0,y:.5},{x:1,y:.5},{x:.5,y:0},{x:.5,y:1}];options.sort((a,b)=>Math.hypot(a.x-u,a.y-v)-Math.hypot(b.x-u,b.y-v));return {nodeId:target.bio.id,...options[0]!};}
 private pointerMove(p:Point,screen:Point){
  if(this.pan){this.canvas.relativePan(screen.subtract(this.pan));this.pan=screen;return;}
  if(!this.drawStart||!this.draft)return;const a=this.drawStart,w=Math.max(1,Math.abs(p.x-a.x)),h=Math.max(1,Math.abs(p.y-a.y));
  if(this.draft instanceof Rect)this.draft.set({left:(a.x+p.x)/2,top:(a.y+p.y)/2,width:w,height:h});
  else if(this.draft instanceof Ellipse)this.draft.set({left:(a.x+p.x)/2,top:(a.y+p.y)/2,rx:w/2,ry:h/2});
  else if(this.draft instanceof Path){let d=`M ${a.x} ${a.y} L ${p.x} ${p.y}`;
   if(this.tool==='polygon'||this.tool==='star'){const count=this.tool==='star'?10:6,c=new Point((a.x+p.x)/2,(a.y+p.y)/2);d=Array.from({length:count},(_,i)=>{const angle=i*Math.PI*2/count-Math.PI/2,f=this.tool==='star'&&i%2?.45:1;return `${i?'L':'M'} ${c.x+Math.cos(angle)*w/2*f} ${c.y+Math.sin(angle)*h/2*f}`;}).join(' ')+' Z';}
   if(this.tool==='bracket')d=`M ${p.x} ${a.y} L ${a.x} ${a.y} L ${a.x} ${p.y} L ${p.x} ${p.y}`;
   if(this.tool==='arc')d=`M ${a.x} ${p.y} C ${a.x} ${a.y} ${p.x} ${a.y} ${p.x} ${p.y}`;
   this.draft._setPath(d);this.draft.set({left:this.draft.pathOffset.x,top:this.draft.pathOffset.y});
  }this.canvas.requestRenderAll();
 }
 private pointerUp(p:Point,target:FabricObject|undefined){
  if(this.pan){this.pan=null;return;}if(!this.draft)return;
  if(this.draft.bio?.link){const actual=target??this.canvas.getObjects().filter(o=>o!==this.draft&&!o.helper&&o.containsPoint(p)).at(-1);this.draft.bio.link.end=this.closestAnchor(actual,p);}
  this.draft.set({selectable:true,evented:true});this.draft.setCoords();const o=this.draft;this.draft=null;this.drawStart=null;this.setTool('select');this.canvas.setActiveObject(o);this.commit();
 }
 private updatePen(){if(this.penDraft)this.canvas.remove(this.penDraft);if(this.penPoints.length<2)return;const d=this.penPoints.map((p,i)=>`${i?'L':'M'} ${p.x} ${p.y}`).join(' ');this.penDraft=new Path(d,{fill:null,stroke:this.color,strokeWidth:2,selectable:false,evented:false});this.penDraft.helper=true;this.canvas.add(this.penDraft);this.canvas.requestRenderAll();}
 private finishPen(closed:boolean){if(this.penDraft)this.canvas.remove(this.penDraft);this.penDraft=null;if(this.penPoints.length>=2){const path=new Path(this.penPoints.map((p,i)=>`${i?'L':'M'} ${p.x} ${p.y}`).join(' ')+(closed?' Z':''),{fill:closed?this.fill:null,stroke:this.color,strokeWidth:2});path.bio=node('path',{name:'펜 경로'});this.canvas.add(path);this.penPoints=[];this.canvas.setActiveObject(path);this.commit();}this.penPoints=[];}
 private tab(name:string){this.q('#edSciencePanel').hidden=name!=='science';this.q('#edAssetPanel').hidden=name!=='assets';this.q('#edLayerPanel').hidden=name!=='layers';this.root.querySelectorAll<HTMLElement>('[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===name));if(name==='layers')this.layers();}
 private async search(){
  const seq=++this.searchSeq,q=this.q<HTMLInputElement>('#edSearch').value,fmt=this.q<HTMLSelectElement>('#edFormat').value;
  const result=await this.h.api<{items:{id:string;title:string;preview_file_id:string;thumbnail:string;formats:string[]}[]}>('/api/search?'+new URLSearchParams({q,format:fmt,limit:'36'}));if(seq!==this.searchSeq)return;
  this.q('#edSearchResults').innerHTML=result.items.map(a=>`<button class="ed-asset" data-asset="${esc(a.id)}" data-file="${esc(a.preview_file_id)}" draggable="true" title="${esc(a.title)}"><img src="${esc(a.thumbnail)}" alt="" loading="lazy"><span>${esc(a.title)}</span><small>${esc(a.formats.join(' / '))}</small></button>`).join('')||'<p class="ed-caption">검색 결과가 없습니다.</p>';
  this.q('#edSearchResults').querySelectorAll<HTMLButtonElement>('[data-file]').forEach(b=>{b.onclick=()=>void this.resolveAsset(b.dataset.asset!,b.dataset.file!,fmt).catch(e=>this.error(e));b.ondragstart=e=>{e.dataTransfer?.setData('text/x-bioart-id',b.dataset.file!);e.dataTransfer?.setData('text/x-bioart-asset',b.dataset.asset!);};});
 }
 private async resolveAsset(aid:string,fid:string,format:string,p?:Point){const a=await this.h.api<{files:{id:string;format:string;status:string}[]}>('/api/assets/'+aid);const f=a.files.find(f=>f.status==='valid'&&f.format===(format||'SVG'));await this.addAsset(f?.id??fid,p);}
 private async addAsset(fid:string,p?:Point){
  if(!this.document)return;const a=await getAsset(this.h.api,fid);const center=p??new Point(this.document.artboard.width/2,this.document.artboard.height/2);
  const n=node('asset',{name:a.title,width:260,height:240,fileId:fid,sha256:a.sha256,transform:{...node('asset').transform,x:center.x,y:center.y},style:{...style(),stroke:'none',strokeWidth:0}});
  const object=await fromNode(n,this.h.api);this.canvas.add(object);this.setTool('select');this.canvas.setActiveObject(object);this.commit();
 }
 private layers(){
  const active=new Set(this.canvas.getActiveObjects().map(o=>o.bio?.id));
  const rows=(objects:FabricObject[],depth=0):string=>[...objects].reverse().filter(o=>!o.helper).map(o=>`<div class="ed-layer ${active.has(o.bio?.id)?'active':''}" style="padding-left:${8+depth*12}px"><button data-select="${o.bio?.id}" title="선택">${o instanceof Group?'▱':'·'} ${esc(o.bio?.name||label[o.bio?.kind??'path'])}</button><button data-visible="${o.bio?.id}" aria-label="${esc(o.bio?.name)} ${o.visible?'숨기기':'보이기'}">${o.visible?'◉':'○'}</button><button data-lock="${o.bio?.id}" aria-label="${esc(o.bio?.name)} ${o.bio?.locked?'잠금 해제':'잠금'}">${o.bio?.locked?'▣':'□'}</button></div>`+(o instanceof Group&&!o.bio?.science?rows(o.getObjects(),depth+1):'')).join('');
  this.q('#edLayers').innerHTML=rows(this.canvas.getObjects())||'<p class="ed-caption">아직 요소가 없습니다.</p>';
  this.q('#edLayers').querySelectorAll<HTMLButtonElement>('button').forEach(b=>b.onclick=()=>{const id=b.dataset.select??b.dataset.visible??b.dataset.lock,o=allObjects(this.canvas).find(o=>o.bio?.id===id);if(!o)return;if(b.dataset.select){let target=o;while(target.group)target=target.group;this.canvas.setActiveObject(target);this.canvas.requestRenderAll();this.properties();}else if(b.dataset.visible){o.visible=!o.visible;if(o.group)o.group.dirty=true;this.commit();}else if(o.bio){o.bio.locked=!o.bio.locked;o.selectable=!o.bio.locked;o.evented=!o.bio.locked;if(o.bio.locked)this.canvas.discardActiveObject();this.commit();}});
 }
 private properties(){
  const box=this.q('#edProperties'),objects=this.canvas.getActiveObjects(),o=this.canvas.getActiveObject();
  const field=(key:string,title:string,val:string|number,type='number',extra='')=>`<label>${title}<input data-prop="${key}" type="${type}" value="${esc(val)}" ${extra}></label>`;
  if(!o||!objects.length){const a=this.document?.artboard;if(!a){box.innerHTML='';return;}box.innerHTML=`<h2>아트보드</h2><p class="ed-caption">크기는 논리 픽셀 단위입니다.</p><div class="ed-fields">${field('boardWidth','너비',a.width,'number','min="100" max="10000"')}${field('boardHeight','높이',a.height,'number','min="100" max="10000"')}${field('background','배경',a.background,'color')}</div><p class="ed-note">라이브러리 원본은 수정하지 않습니다. 저장한 도해는 이 작업 폴더에서 다시 열 수 있습니다.</p><h3>빠른 시작</h3><button id="edQuickText">텍스트 추가</button><button id="edQuickRect">도형 추가</button>`;
   this.q('#edQuickText').onclick=()=>{this.setTool('text');this.message('캔버스에서 텍스트를 놓을 위치를 클릭하세요.');};this.q('#edQuickRect').onclick=()=>this.setTool('rect');
  }else{
   const n=toNode(o),multi=objects.length>1;
   box.innerHTML=`<h2>${multi?objects.length+'개 선택':esc(label[n.kind])}</h2>${multi?'':field('name','레이어 이름',n.name,'text')}${n.science?`<h3>${esc(scienceName(n.science))}</h3><div class="ed-buttons"><button data-edit="science">생성 설정 편집</button><button data-edit="expandScience">개별 도형 편집 사본</button>${n.science.type==='brush'?'<button data-edit="brushPath">브러시 기준 경로 꺼내기</button>':''}</div><p class="ed-note">${n.science.type==='inset'?(n.science.live?'원본 변경 자동 반영':'고정 삽화'): '설정과 벡터 결과가 함께 저장됩니다.'}</p>`:''}<div class="ed-fields">${field('x','가로 위치',Math.round(o.left))}${field('y','세로 위치',Math.round(o.top))}${field('width','너비',Math.round(o.getScaledWidth()),'number','min="1"')}${field('height','높이',Math.round(o.getScaledHeight()),'number','min="1"')}${field('angle','회전 °',Math.round(o.angle))}${field('opacity','불투명도 %',Math.round(o.opacity*100),'number','min="0" max="100"')}</div><div class="ed-buttons"><button data-edit="flipX">좌우 반전</button><button data-edit="flipY">상하 반전</button></div>
   ${n.science||['asset','image'].includes(n.kind)?'':`<h3>색과 선</h3><div class="ed-fields">${field('fill','채움',typeof o.fill==='string'&&/^#[a-f0-9]{6}$/i.test(o.fill)?o.fill:'#b8d9c7','color')}${field('stroke','선',typeof o.stroke==='string'&&/^#[a-f0-9]{6}$/i.test(o.stroke)?o.stroke:'#276a57','color')}${field('strokeWidth','선 굵기',o.strokeWidth,'number','min="0" max="500" step="0.5"')}</div><div class="ed-buttons"><button data-edit="noFill">채움 없음</button><button data-edit="gradient">그라디언트</button><button data-edit="dash">점선 전환</button><button data-edit="copyStyle">스타일 복사</button><button data-edit="pasteStyle">스타일 붙여넣기</button></div><div class="ed-fields"><label>선 끝<select data-prop="lineCap">${['butt','round','square'].map((v,i)=>`<option value="${v}" ${o.strokeLineCap===v?'selected':''}>${['평평하게','둥글게','사각형'][i]}</option>`).join('')}</select></label><label>선 연결<select data-prop="lineJoin">${['miter','round','bevel'].map((v,i)=>`<option value="${v}" ${o.strokeLineJoin===v?'selected':''}>${['뾰족하게','둥글게','모따기'][i]}</option>`).join('')}</select></label></div>`}
   ${o instanceof IText?`<h3>텍스트</h3><textarea id="edText" aria-label="텍스트 내용">${esc(o.text)}</textarea><div class="ed-fields">${field('fontSize','글자 크기',o.fontSize)}<label>서체<select data-prop="fontFamily"><option ${o.fontFamily==='Helvetica Neue'?'selected':''}>Helvetica Neue</option><option ${o.fontFamily==='Georgia'?'selected':''}>Georgia</option><option ${o.fontFamily==='Apple SD Gothic Neo'?'selected':''}>Apple SD Gothic Neo</option><option ${o.fontFamily==='Times New Roman'?'selected':''}>Times New Roman</option></select></label></div><div class="ed-buttons"><button data-edit="bold">굵게</button><button data-edit="italic">기울임</button><button data-edit="textLeft">왼쪽</button><button data-edit="textCenter">가운데</button><button data-edit="textRight">오른쪽</button></div>`:''}
   ${o instanceof Rect?field('radius','모서리 반경',o.rx):''}
   ${o instanceof Path?`<h3>경로</h3><p class="ed-caption">점 ${this.directIndex+1} 선택 · 점 편집 도구에서 핸들을 끌어 곡선을 조절하세요.</p><div class="ed-buttons"><button data-edit="direct">점 편집</button><button data-edit="addPoint">점 추가</button><button data-edit="removePoint">선택 점 삭제</button><button data-edit="curvePoint">곡선으로</button><button data-edit="cornerPoint">직선으로</button><button data-edit="closePath">경로 닫기</button><button data-edit="simplify">단순화</button></div>`:''}
   ${n.link?`<h3>연결선</h3><label>경로<select data-prop="linkMode">${[['straight','직선'],['curve','곡선'],['elbow','직각']].map(([v,l])=>`<option value="${v}" ${n.link?.mode===v?'selected':''}>${l}</option>`).join('')}</select></label>${(['startHead','endHead'] as const).map(k=>`<label>${k==='startHead'?'시작':'끝'}<select data-prop="${k}">${[['none','없음'],['arrow','화살표'],['bar','억제선']].map(([v,l])=>`<option value="${v}" ${n.link?.[k]===v?'selected':''}>${l}</option>`).join('')}</select></label>`).join('')}<p class="ed-caption">${n.link.start?'시작 연결됨':'시작 자유'} · ${n.link.end?'끝 연결됨':'끝 자유'}</p><button data-edit="detach">객체 연결 해제</button>`:''}
   <h3>가공</h3><div class="ed-buttons"><button data-edit="unite">합치기</button><button data-edit="subtract">빼기</button><button data-edit="intersect">교집합</button><button data-edit="exclude">제외</button><button data-edit="divide">분할</button><button data-edit="mask">클리핑 마스크</button><button data-edit="unmask">마스크 해제</button></div>
   ${n.kind==='asset'?`<h3>원본 자료</h3><p class="ed-caption">파일 ${esc(n.fileId)} · 체크섬 보존</p><button data-edit="explode">SVG 편집용 복사본</button><p class="ed-note">복사본은 경로 단위로 편집됩니다. 원본 파일은 보존됩니다.</p>`:''}
   ${n.sourceFileIds.length?`<p class="ed-note">원본 참조: ${esc(n.sourceFileIds.join(', '))}</p>`:''}`;
   box.querySelectorAll<HTMLButtonElement>('[data-edit]').forEach(b=>b.onclick=()=>void this.edit(b.dataset.edit??'').catch(e=>this.error(e)));
   const text=box.querySelector<HTMLTextAreaElement>('#edText');if(text&&o instanceof IText)text.oninput=()=>{o.set('text',text.value);o.setCoords();this.commit(false);};
  }
  box.querySelectorAll<HTMLInputElement|HTMLSelectElement>('[data-prop]').forEach(input=>input.onchange=()=>{try{this.property(input.dataset.prop??'',input.value);}catch(e){this.error(e);this.properties();}});
 }
 private property(key:string,value:string){
  if(!this.document)return;const num=Number(value);if(!Number.isFinite(num)&&!['fill','stroke','background','name','fontFamily','linkMode','startHead','endHead','lineCap','lineJoin'].includes(key))throw Error('유효한 숫자를 입력하세요.');
  if(key==='boardWidth'||key==='boardHeight'){if(num<100||num>10000)throw Error('아트보드 크기는 100–10,000입니다.');this.document.artboard[key==='boardWidth'?'width':'height']=num;this.commit();this.fit();return;}
  if(key==='background'){this.document.artboard.background=value;this.commit();return;}
  const active=this.canvas.getActiveObject();if(!active)return;const targets=['x','y','width','height','angle'].includes(key)?[active]:this.canvas.getActiveObjects();
  for(const o of targets){
   if(key==='name'&&o.bio)o.bio.name=value;
   else if(key==='x'||key==='y')o.set(key==='x'?'left':'top',num);
   else if(key==='width'||key==='height'){if(num<=0||num>10000)throw Error('크기는 1–10,000입니다.');o.set(key==='width'?'scaleX':'scaleY',num/Math.max(1,key==='width'?o.width:o.height));}
   else if(key==='angle')o.set('angle',num);
   else if(key==='opacity')o.set('opacity',Math.min(1,Math.max(0,num/100)));
   else if(key==='fill'||key==='stroke')o.set(key,value);
   else if(key==='lineCap')o.set('strokeLineCap',value as 'butt'|'round'|'square');
   else if(key==='lineJoin')o.set('strokeLineJoin',value as 'miter'|'round'|'bevel');
   else if(key==='strokeWidth')o.set('strokeWidth',Math.min(500,Math.max(0,num)));
   else if(key==='fontSize'&&o instanceof IText)o.set('fontSize',Math.min(1000,Math.max(1,num)));
   else if(key==='fontFamily'&&o instanceof IText)o.set('fontFamily',value);
   else if(key==='radius'&&o instanceof Rect)o.set({rx:num,ry:num});
   else if(o.bio?.link){if(key==='linkMode')o.bio.link.mode=value as 'straight'|'curve'|'elbow';else if(key==='startHead'||key==='endHead')o.bio.link[key]=value as 'none'|'arrow'|'bar';}
   o.dirty=true;o.setCoords();
  }this.commit();
 }
 private async edit(action:string){
  const objects=this.canvas.getActiveObjects(),o=this.canvas.getActiveObject();if(!o)return;
  if(action==='science'&&o.bio?.science){this.scienceUI.edit(o.bio.science,toNode(o));return;}
  if(action==='expandScience'){const copy=remap([toNode(o,true)])[0]!;for(const n of walk([copy]))n.science=null;copy.name+=' · 개별 편집 사본';copy.transform.x+=24;copy.transform.y+=24;await this.putScience([copy]);this.message('생성기 원본을 보존하고 사본을 만들었습니다. 그룹 해제 후 각 도형을 편집하세요.');return;}
  if(action==='brushPath'&&o.bio?.science?.type==='brush'){const p=new Path(o.bio.science.path,{fill:null,stroke:this.color,strokeWidth:2});p.bio=node('path',{name:'브러시 기준 경로'});const n=toNode(p);n.transform=toNode(o,true).transform;await this.putScience([n]);this.setTool('direct');this.message('기준 경로 사본의 점을 편집한 뒤 과학 제작에서 선택 경로에 적용하세요.');return;}
  if(action==='direct'){this.setTool('direct');return;}
  if(action==='explode'){
   if(!o.bio?.fileId)throw Error('SVG 원본을 선택하세요.');const data=await getAsset(this.h.api,o.bio.fileId);if(!data.svg)throw Error('PNG는 내부 경로가 없습니다. SVG 자료를 선택하세요.');
   const copy=await editableSVG(data.svg,toNode(o));
   if(this.document)await this.h.api('/api/documents/validate',{...this.document,nodes:[toNode(copy)]});
   copy.left+=30;copy.top+=30;this.canvas.add(copy);this.canvas.setActiveObject(copy);this.commit();this.message('편집용 복사본을 만들었습니다. 그룹 해제 후 개별 경로를 선택하세요.');return;
  }
  if(['unite','subtract','intersect','exclude','divide'].includes(action)){
   if(objects.some(x=>!['rect','ellipse','path'].includes(x.bio?.kind??'')))throw Error('도형과 경로만 선택하세요.');this.canvas.discardActiveObject();const path=booleanPath(objects,action as 'unite'|'subtract'|'intersect'|'exclude'|'divide');this.canvas.remove(...objects);this.canvas.add(path);this.canvas.setActiveObject(path);this.commit();return;
  }
  if(action==='mask'){
   if(objects.length!==2)throw Error('대상과 마스크 도형을 두 개 선택하세요. 맨 앞 도형이 마스크가 됩니다.');this.canvas.discardActiveObject();const ordered=this.canvas.getObjects().filter(x=>objects.includes(x)),target=ordered[0]!,mask=ordered[1]!;
   if(!['rect','ellipse','path'].includes(mask.bio?.kind??''))throw Error('마스크는 도형 또는 경로여야 합니다.');
   util.applyTransformToObject(mask,util.multiplyTransformMatrices(util.invertTransform(target.calcTransformMatrix()),mask.calcTransformMatrix()));this.canvas.remove(mask);target.clipPath=mask;target.dirty=true;this.canvas.setActiveObject(target);this.commit();return;
  }
  if(action==='unmask'){for(const x of objects)if(x.clipPath instanceof FabricObject){const mask=x.clipPath;util.applyTransformToObject(mask,util.multiplyTransformMatrices(x.calcTransformMatrix(),mask.calcOwnMatrix()));delete x.clipPath;x.dirty=true;this.canvas.add(mask);}this.commit();return;}
  if(action==='copyStyle'){this.copiedStyle=toNode(objects[0]!).style;this.message('스타일을 복사했습니다.');return;}
  if(action==='pasteStyle'){if(!this.copiedStyle)return;for(const x of objects){const n=toNode(x);n.style=structuredClone(this.copiedStyle);const replacement=await fromNode(n,this.h.api);const index=this.canvas.getObjects().indexOf(x);this.canvas.remove(x);this.canvas.insertAt(index,replacement);}this.commit();return;}
  if(o instanceof Path&&['addPoint','removePoint','curvePoint','cornerPoint','closePath','simplify'].includes(action)){
   if(o.bio?.link)throw Error('연결선은 경로 모양 설정으로 바꾸세요.');
   if(action==='simplify'){const replacement=simplify(o);this.canvas.remove(o);this.canvas.add(replacement);this.canvas.setActiveObject(replacement);this.commit();return;}
   const p=structuredClone(o.path),i=Math.min(Math.max(1,this.directIndex),p.length-1),c=p[i],prev=p[i-1];if(!c||!prev)return;
   const x=Number(c.at(-2)),y=Number(c.at(-1)),px=Number(prev.at(-2)),py=Number(prev.at(-1));
   if(action==='addPoint')p.splice(i,0,['L',(x+px)/2,(y+py)/2]);
   if(action==='removePoint'&&p.length>2)p.splice(i,1);
   if(action==='curvePoint'&&Number.isFinite(x))p[i]=['C',px+(x-px)/3,py-50,px+(x-px)*2/3,y-50,x,y];
   if(action==='cornerPoint'&&Number.isFinite(x))p[i]=['L',x,y];
   if(action==='closePath'&&p.at(-1)?.[0]!=='Z')p.push(['Z']);
   const before=o.pathOffset.clone(),matrix=o.calcTransformMatrix();o._setPath(p);const delta=o.pathOffset.subtract(before);matrix[4]+=matrix[0]*delta.x+matrix[2]*delta.y;matrix[5]+=matrix[1]*delta.x+matrix[3]*delta.y;util.applyTransformToObject(o,matrix);o.controls=controlsUtils.createPathControls(o);o.setCoords();this.commit();return;
  }
  for(const x of objects){
   if(action==='flipX'||action==='flipY')x.set(action,!x[action]);
   if(action==='noFill')x.set('fill',null);
   if(action==='dash')x.set('strokeDashArray',x.strokeDashArray?.length?[]:[10,6]);
   if(action==='gradient'){const n=toNode(x);n.style.fill={type:'linear',units:'pixels',coords:{x1:0,y1:0,x2:x.width,y2:x.height},stops:[{offset:0,color:this.fill,opacity:1},{offset:1,color:this.color,opacity:1}],offsetX:0,offsetY:0,matrix:null};const replacement=await fromNode(n,this.h.api);const at=this.canvas.getObjects().indexOf(x);this.canvas.remove(x);this.canvas.insertAt(at,replacement);this.canvas.setActiveObject(replacement);}
   if(x instanceof IText){if(action==='bold')x.set('fontWeight',x.fontWeight==='bold'?'normal':'bold');if(action==='italic')x.set('fontStyle',x.fontStyle==='italic'?'normal':'italic');if(action.startsWith('text'))x.set('textAlign',action==='textCenter'?'center':action==='textRight'?'right':'left');}
   if(action==='detach'&&x.bio?.link){x.bio.link.start=null;x.bio.link.end=null;}
   x.dirty=true;x.setCoords();
  }this.commit();
 }
 private align(mode:string){
  const objects=this.canvas.getActiveObjects();if(objects.length<2){this.message('정렬할 요소를 두 개 이상 선택하세요.');return;}
  this.canvas.discardActiveObject();const boxes=objects.map(o=>o.getBoundingRect()),left=Math.min(...boxes.map(b=>b.left)),right=Math.max(...boxes.map(b=>b.left+b.width)),top=Math.min(...boxes.map(b=>b.top)),bottom=Math.max(...boxes.map(b=>b.top+b.height));
  if(mode==='horizontal'||mode==='vertical'){
   const horizontal=mode==='horizontal',sorted=[...objects].sort((a,b)=>(horizontal?a.getBoundingRect().left:a.getBoundingRect().top)-(horizontal?b.getBoundingRect().left:b.getBoundingRect().top));
   const sum=sorted.reduce((s,o)=>s+(horizontal?o.getBoundingRect().width:o.getBoundingRect().height),0),gap=((horizontal?right-left:bottom-top)-sum)/(sorted.length-1);let pos=horizontal?left:top;
   for(const o of sorted){const b=o.getBoundingRect();if(horizontal)o.left+=pos-b.left;else o.top+=pos-b.top;pos+=(horizontal?b.width:b.height)+gap;}
  }else objects.forEach((o,i)=>{const b=boxes[i]!;if(mode==='left')o.left+=left-b.left;if(mode==='right')o.left+=right-b.left-b.width;if(mode==='center')o.left+=(left+right)/2-b.left-b.width/2;if(mode==='top')o.top+=top-b.top;if(mode==='bottom')o.top+=bottom-b.top-b.height;if(mode==='middle')o.top+=(top+bottom)/2-b.top-b.height/2;});
  objects.forEach(o=>o.setCoords());this.canvas.setActiveObject(new ActiveSelection(objects,{canvas:this.canvas}));this.commit();
 }
 private async action(action:string){
  if(action==='back'){await this.flush();this.root.hidden=true;this.active=false;document.body.classList.remove('editor-open');return;}
  if(action==='new'){await this.newDocument();return;}
  if(action==='portable'){await portableDialog({api:this.h.api,save:async()=>{await this.flush();if(!this.document)throw Error('도해를 먼저 여세요.');return structuredClone(this.document);},accept:async d=>{await this.accept(d);await this.projectList();},dialog:(title,body)=>{this.dialog(title,body);return this.q('#edDialogBody');},close:()=>this.q<HTMLDialogElement>('#edDialog').close(),showExport:this.h.showExport});return;}
  if(action==='export'){await this.publication.open();return;}
  if(action==='legacy'){const scenes=await this.h.api<{id:string;title:string;revision:number}[]>('/api/documents/legacy');this.dialog('이전 도해 가져오기',`<p>기존 도해는 보존하고 편집 가능한 새 사본을 만듭니다.</p><div class="ed-legacy-list">${scenes.map(s=>`<button data-legacy="${s.id}">${esc(s.title)} <small>${s.id} · 수정 ${s.revision}</small></button>`).join('')||'<p>기존 도해가 없습니다.</p>'}</div>`);this.root.querySelectorAll<HTMLButtonElement>('[data-legacy]').forEach(b=>b.onclick=()=>{void (async()=>{await this.flush();const d=await this.h.api<FigureDocument>('/api/documents/migrate',{scene_id:b.dataset.legacy});await this.accept(d);await this.projectList();this.q<HTMLDialogElement>('#edDialog').close();})().catch(e=>this.error(e));});return;}
  if(action==='fit'){this.fit();return;}
  if(action==='zoom-in'||action==='zoom-out'){this.canvas.zoomToPoint(new Point(this.canvas.width/2,this.canvas.height/2),Math.min(5,Math.max(.08,this.canvas.getZoom()*(action==='zoom-in'?1.2:1/1.2))));this.zoomLabel();return;}
  if(action==='toggle-assets'||action==='toggle-properties'){this.root.classList.toggle(action==='toggle-assets'?'ed-hide-assets':'ed-hide-properties');this.resize();return;}
  if(action==='undo'||action==='redo'){const snapshot=action==='undo'?this.history.undo():this.history.redo();if(snapshot&&this.document){Object.assign(this.document,JSON.parse(snapshot));await this.renderDocument();this.q<HTMLInputElement>('#edTitle').value=this.document.title;this.properties();this.layers();this.dirty=true;this.status('저장 중…');void this.persist();}return;}
  const objects=this.canvas.getActiveObjects(),o=this.canvas.getActiveObject();if(!o)return;
  if(action==='delete'){this.canvas.discardActiveObject();this.canvas.remove(...objects);this.commit();return;}
  if(action==='duplicate'){this.clipboard=remap(objects.map(x=>toNode(x,true)));await this.paste();return;}
  if(action==='group'){
   if(objects.length<2)return;this.canvas.discardActiveObject();this.canvas.remove(...objects);const group=new Group(objects);group.bio=node('group',{name:'그룹'});this.canvas.add(group);this.canvas.setActiveObject(group);this.commit();return;
  }
  if(action==='ungroup'&&o.bio?.science){await this.edit('expandScience');return;}
  if(action==='ungroup'&&o instanceof Group&&!(o instanceof ActiveSelection)){const children=o.removeAll();this.canvas.remove(o);this.canvas.add(...children);this.canvas.setActiveObject(new ActiveSelection(children,{canvas:this.canvas}));this.commit();return;}
  if(action==='front'){this.canvas.discardActiveObject();for(const x of objects)this.canvas.bringObjectToFront(x);this.commit();return;}
  if(action==='backward'){this.canvas.discardActiveObject();for(const x of objects)this.canvas.sendObjectBackwards(x);this.commit();}
 }
 private async paste(){if(!this.clipboard.length)return;const nodes=remap(this.clipboard);for(const n of nodes){n.transform.x+=24;n.transform.y+=24;}const objects=await Promise.all(nodes.map(n=>fromNode(n,this.h.api)));this.canvas.discardActiveObject();this.canvas.add(...objects);this.canvas.setActiveObject(objects.length===1?objects[0]!:new ActiveSelection(objects,{canvas:this.canvas}));this.commit();}
 private keys(e:KeyboardEvent){
  if(!this.active||this.q<HTMLDialogElement>('#edDialog').open||document.querySelector<HTMLDialogElement>('#modal')?.open)return;
  const target=e.target as HTMLElement,typing=['INPUT','TEXTAREA','SELECT'].includes(target.tagName)||(this.canvas.getActiveObject() instanceof IText&&(this.canvas.getActiveObject() as IText).isEditing);
  if(typing){e.stopPropagation();return;}
  const mod=e.metaKey||e.ctrlKey,k=e.key.toLowerCase();let action='';
  if(mod&&k==='z')action=e.shiftKey?'redo':'undo';else if(mod&&k==='s'){e.preventDefault();e.stopImmediatePropagation();void this.flush().catch(x=>this.error(x));return;}
  else if(mod&&k==='d')action='duplicate';else if(mod&&k==='g')action=e.shiftKey?'ungroup':'group';else if(k==='delete'||k==='backspace')action='delete';
  else if(mod&&k==='a'){const all=this.canvas.getObjects().filter(o=>!o.helper&&o.visible&&!o.bio?.locked);this.canvas.setActiveObject(new ActiveSelection(all,{canvas:this.canvas}));this.canvas.requestRenderAll();}
  else if(mod&&k==='c'){this.clipboard=this.canvas.getActiveObjects().map(o=>toNode(o,true));this.message('선택한 요소를 복사했습니다.');}
  else if(mod&&k==='v'){void this.paste().catch(x=>this.error(x));}
  else if(k==='escape'){this.penPoints=[];if(this.penDraft)this.canvas.remove(this.penDraft);this.penDraft=null;this.canvas.discardActiveObject();this.setTool('select');}
  else if(k==='enter'&&this.tool==='pen'){this.finishPen(e.shiftKey);this.setTool('select');}
  else if(['arrowleft','arrowright','arrowup','arrowdown'].includes(k)){const o=this.canvas.getActiveObject();if(o){const step=e.shiftKey?10:1;o.left+=(k==='arrowright'?step:k==='arrowleft'?-step:0);o.top+=(k==='arrowdown'?step:k==='arrowup'?-step:0);o.setCoords();this.commit();}}
  else if(k===' '){const previous=this.tool;this.setTool('hand');window.addEventListener('keyup',()=>this.setTool(previous),{once:true});}
  else if(!mod){const tools:Record<string,Tool>={v:'select',a:'direct',h:'hand',r:'rect',o:'ellipse',l:'line',c:'arrow',p:'pen',b:'pencil',t:'text',i:'eyedropper'};if(tools[k])this.setTool(tools[k]);else return;}
  else return;
  e.preventDefault();e.stopImmediatePropagation();if(action)void this.action(action).catch(x=>this.error(x));
 }
 private async putScience(nodes:Node[],replace?:string){
  if(!this.document)return;
  const previous=replace?this.canvas.getObjects().find(o=>o.bio?.id===replace):undefined;
  if(replace&&!previous)throw Error('편집할 객체를 다시 선택하세요.');
  const candidate={...this.document,nodes:[...serialize(this.canvas).filter(n=>n.id!==replace),...nodes]};
  detachMissing(candidate.nodes);refreshInsets(candidate.nodes);await this.h.api('/api/documents/validate',candidate);
  const objects=await Promise.all(nodes.map(n=>fromNode(n,this.h.api)));this.canvas.discardActiveObject();
  const index=previous?this.canvas.getObjects().indexOf(previous):this.canvas.getObjects().length;
  if(previous)this.canvas.remove(previous);this.canvas.insertAt(index,...objects);this.setTool('select');
  this.canvas.setActiveObject(objects.length===1?objects[0]!:new ActiveSelection(objects,{canvas:this.canvas}));this.commit();
 }
 private async renderInsets(ids:string[]){
  const epoch=++this.insetEpoch;const updates=await Promise.all(ids.map(async id=>{const n=this.document?walk(this.document.nodes).find(n=>n.id===id):undefined;return n?{id,object:await fromNode(n,this.h.api)}:null;}));
  if(epoch!==this.insetEpoch)return;
  for(const update of updates){if(!update)continue;const old=allObjects(this.canvas).find(o=>o.bio?.id===update.id);if(!old)continue;const selected=this.canvas.getActiveObject()===old;if(old.group){const group=old.group,index=group.getObjects().indexOf(old);group.remove(old);group.insertAt(index,update.object);group.dirty=true;}else{const index=this.canvas.getObjects().indexOf(old);this.canvas.remove(old);this.canvas.insertAt(index,update.object);}if(selected)this.canvas.setActiveObject(update.object);}
  this.canvas.requestRenderAll();
 }
 private async reloadCurrentSnapshot(){if(this.document){await this.renderDocument();this.properties();}}
 private dialog(title:string,body:string){this.q('#edDialogTitle').textContent=title;this.q('#edDialogBody').innerHTML=body;const d=this.q<HTMLDialogElement>('#edDialog');if(!d.open)d.showModal();}
}
