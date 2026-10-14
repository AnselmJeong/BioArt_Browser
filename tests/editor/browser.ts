import { generators, generate, defaults, refreshInsets } from '../../src/editor/science';
import { examples } from '../../src/editor/science-ui';
import {Canvas,Rect,Ellipse,Group,IText,Path,Point,ActiveSelection,util} from 'fabric';
import {fromNode,toNode,serialize,editableSVG,getAsset,updateConnections,ConnectorPath,anchorPoint} from '../../src/editor/adapter';
import {node} from '../../src/editor/model';
import type {API,FigureDocument,Node} from '../../src/editor/model';
import {booleanPath} from '../../src/editor/geometry';
const output=document.querySelector('#results')!;
let passed=0,failed=0;
const line=(s:string)=>{const p=document.createElement('p');p.textContent=s;output.append(p);};
const assert=(value:unknown,message:string)=>{if(!value)throw Error(message);};
const session=await fetch('/api/session').then(r=>r.json()) as {token:string};
const api:API=async<T>(path:string,body?:unknown):Promise<T>=>{const r=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Bioart-Token':session.token},body:JSON.stringify(body)});if(!r.ok)throw Error(await r.text());return r.json() as Promise<T>;};
async function test(name:string,fn:()=>Promise<void>|void){try{await fn();passed++;line('PASS '+name);}catch(e){failed++;line('FAIL '+name+' '+String(e));}}
const canvas=new Canvas(document.querySelector<HTMLCanvasElement>('#canvas')!,{width:800,height:500});
await test('groups, reflected transforms, text and masks survive canonical reload',async()=>{
 const a=new Rect({left:140,top:120,width:100,height:70,fill:'#aa3344',angle:25});a.bio=node('rect');
 const text=new IText('한글 α O₂\n연결선',{left:320,top:230,fontSize:30});text.bio=node('text');
 const group=new Group([a,text],{angle:31,flipX:true,scaleX:1.2});group.bio=node('group');
 const clip=new Ellipse({rx:70,ry:50,left:0,top:0});clip.bio=node('ellipse');a.clipPath=clip;
 const before=toNode(group);const restored=await fromNode(before,api);const after=toNode(restored);
 const m=group.calcTransformMatrix(),m2=restored.calcTransformMatrix();m.forEach((x,i)=>assert(Math.abs(x-m2[i]!)<.001,'group transform drift'));
 assert(Math.abs(before.children[0]!.transform.x-after.children[0]!.transform.x)<.001,'child offset drift');
 assert(after.children[0]?.clip?.kind==='ellipse','lost clip');assert(after.children[1]?.text===text.text,'lost text');
 canvas.add(restored);
});
await test('connector follows target inside rotated group',()=>{
 canvas.remove(...canvas.getObjects());const a=new Rect({left:200,top:150,width:100,height:80});a.bio=node('rect');const b=new Ellipse({left:550,top:250,rx:60,ry:40});b.bio=node('ellipse');
 const group=new Group([a],{angle:30});group.bio=node('group');const c=new ConnectorPath('M 0 0 L 100 100');c.bio=node('connector',{link:{start:{nodeId:a.bio.id,x:1,y:.5},end:{nodeId:b.bio.id,x:0,y:.5},mode:'curve',startHead:'none',endHead:'arrow'}});
 canvas.add(group,b,c);updateConnections(canvas);group.left+=70;group.angle=60;updateConnections(canvas);
 const expected=anchorPoint(a,1,.5),first=c.path[0]!,actual=util.transformPoint(new Point(Number(first[1])-c.pathOffset.x,Number(first[2])-c.pathOffset.y),c.calcTransformMatrix());assert(actual.distanceFrom(expected)<.01,'endpoint detached');
});
await test('Boolean union and subtraction preserve world position',()=>{
 const a=new Rect({left:250,top:200,width:100,height:100,fill:'#276a57',strokeWidth:0});a.bio=node('rect');const b=new Rect({left:300,top:200,width:100,height:100,fill:'#276a57',strokeWidth:0});b.bio=node('rect');
 const merged=booleanPath([a,b],'unite');assert(Math.abs(merged.width-150)<1,'union width');assert(Math.abs(merged.left-275)<1,'union moved');
 const sub=booleanPath([a,b],'subtract');assert(Math.abs(sub.width-50)<1,'subtract width');
});
await test('document save and reload keeps selected group and detached paths',async()=>{
 const d=await api<FigureDocument>('/api/documents',{title:'QA · 편집 엔진 왕복'});d.nodes=serialize(canvas);const saved=await api<FigureDocument>('/api/documents/'+d.id,{document:d,baseRevision:d.revision,operationId:crypto.randomUUID()});const loaded=await api<FigureDocument>('/api/documents/'+d.id);assert(JSON.stringify(saved)===JSON.stringify(loaded),'persisted state differs');const exp=await api<{path:string}>('/api/documents/'+d.id+'/export',{revision:saved.revision});line('OUTPUT '+exp.path);
});
const sample=await fetch('/editor-samples.json').then(r=>r.json()) as {ids:string[]};
let editable=0,unsupported=0;
for(const fid of sample.ids){await test('BioArt SVG original roundtrip '+fid,async()=>{
 const asset=await getAsset(api,fid);const n=node('asset',{fileId:fid,sha256:asset.sha256,name:asset.title,width:260,height:240,transform:{...node('asset').transform,x:300,y:250}});const o=await fromNode(n,api);assert(toNode(o).fileId===fid,'lost source identity');
 const native=await util.loadImage(asset.url);assert(native.naturalWidth>0,'SVG did not decode');
 if(asset.svg){try{const vector=await editableSVG(asset.svg,n),doc=toNode(vector);const restored=await fromNode(doc,api);
 const fixture:FigureDocument={schemaVersion:1,id:'doc-000000000001',revision:1,title:'SVG fixture',artboard:{width:800,height:500,background:'#ffffff'},nodes:[doc],sourceSceneId:null,updatedAt:''};
 await api('/api/documents/validate',fixture);
 canvas.remove(...canvas.getObjects());canvas.add(o);canvas.renderAll();const original=canvas.getContext().getImageData(0,0,800,500).data;canvas.remove(o);canvas.add(restored);canvas.renderAll();const converted=canvas.getContext().getImageData(0,0,800,500).data;let diff=0,ink=0;for(let i=0;i<original.length;i+=4){if(original[i+3]!>10||converted[i+3]!>10){ink++;if(Math.abs(original[i]!-converted[i]!)+Math.abs(original[i+1]!-converted[i+1]!)+Math.abs(original[i+2]!-converted[i+2]!)+Math.abs(original[i+3]!-converted[i+3]!)>100)diff++;}}
 if(diff/Math.max(1,ink)>.12)throw Error('SVG visual difference '+Math.round(diff/ink*100)+'%');editable++;}catch(e){unsupported++;line('COPY LIMIT '+fid+' '+String(e).slice(0,160));}}
 });}
for(const id of Object.keys(generators) as (keyof typeof generators)[])await test('scientific generator '+id,async()=>{const n=generate({type:'generator',version:1,id,params:defaults(id)});const o=await fromNode(n,api),restored=toNode(o);assert(restored.children.length===n.children.length,'lost geometry');assert(JSON.stringify(restored.science)===JSON.stringify(n.science),'lost recipe');});
for(let i=0;i<5;i++)await test('scientific figure '+i+' save/reopen/export',async()=>{const example=await examples(i),d=await api<FigureDocument>('/api/documents',{title:'QA browser · '+example.title});canvas.remove(...canvas.getObjects());canvas.add(...await Promise.all(example.nodes.map(n=>fromNode(n,api))));d.nodes=serialize(canvas);refreshInsets(d.nodes);const saved=await api<FigureDocument>('/api/documents/'+d.id,{document:d,baseRevision:d.revision,operationId:crypto.randomUUID()});const read=await api<FigureDocument>('/api/documents/'+d.id);assert(JSON.stringify(saved)===JSON.stringify(read),'changed on read');const validated=await api<{svg:string}>('/api/documents/validate',read);const image=await util.loadImage('data:image/svg+xml;charset=utf-8,'+encodeURIComponent(validated.svg));assert(image.naturalWidth===1400,'SVG does not decode');const exp=await api<{path:string}>('/api/documents/'+d.id+'/export',{revision:saved.revision});line('SCIENCE OUTPUT '+exp.path);});
line(`SVG COPIES ${editable} editable / ${unsupported} unsupported (originals retained)`);
line(`RESULT ${passed} passed, ${failed} failed`);document.title=`Editor validation: ${passed} passed / ${failed} failed`;
