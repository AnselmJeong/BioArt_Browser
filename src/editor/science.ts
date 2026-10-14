/** Versioned scientific schematics. Saved geometry is authoritative until explicit regeneration. */
import paper from 'paper/dist/paper-core';
import { Path } from 'fabric';
import { node, style, transform, walk } from './model';
import type { Node } from './model';
export const generators={membrane:'세포막',vesicle:'소포 · 리포좀',cell:'세포와 핵',receptor:'막 수용체',antibody:'항체',dna:'DNA 이중 나선',rna:'RNA 단일 가닥',particles:'입자 군집',hydrogel:'하이드로젤',tube:'실험 튜브'} as const;
export type GeneratorId=keyof typeof generators;
export const brushes={membrane:'막 이중층',beads:'분자 사슬',dna:'DNA',rna:'RNA',fiber:'섬유'} as const;
export type BrushId=keyof typeof brushes;
export interface Parameters {width:number;height:number;spacing:number;thickness:number;count:number;seed:number;color:string;accent:string}
export type Science =
 | {type:'generator';version:1;id:GeneratorId;params:Parameters}
 | {type:'brush';version:1;id:BrushId;params:Parameters;path:string}
 | {type:'equation';version:1;latex:string;size:number;color:string}
 | {type:'table';version:1;cells:string[][];cellWidth:number;rowHeight:number;fontSize:number;header:boolean;color:string;accent:string}
 | {type:'panels';version:1;rows:number;columns:number;panelWidth:number;panelHeight:number;gap:number;startLabel:string;color:string}
 | {type:'inset';version:1;sourceId:string|null;live:boolean;centerX:number;centerY:number;span:number;size:number;shape:'circle'|'rect';color:string};
export function defaults(id:GeneratorId='membrane'):Parameters{return {width:id==='cell'||id==='vesicle'?260:360,height:id==='cell'||id==='vesicle'?260:id==='tube'?240:140,spacing:18,thickness:36,count:18,seed:17,color:'#276a57',accent:'#d99b73'};}
const scope=new paper.PaperScope();scope.setup(new scope.Size(1,1));
const paint=(fill:string,stroke='none',strokeWidth=0)=>({...style(),fill,stroke,strokeWidth});
const at=(x:number,y:number,angle=0)=>({...transform(),x,y,angle});
export const ellipse=(x:number,y:number,w:number,h:number,fill:string,stroke='none',sw=0)=>node('ellipse',{width:w,height:h,transform:at(x,y),style:paint(fill,stroke,sw)});
export const rect=(x:number,y:number,w:number,h:number,fill:string,stroke='none',sw=0)=>node('rect',{width:w,height:h,transform:at(x,y),style:paint(fill,stroke,sw)});
export function path(d:string,color:string,sw=2,fill='none'):Node{const p=new Path(d);return node('path',{path:d,pathOffset:[p.pathOffset.x,p.pathOffset.y],width:p.width,height:p.height,transform:at(p.pathOffset.x,p.pathOffset.y),style:paint(fill,color,sw)});}
export function text(value:string,x:number,y:number,size=24,color='#243e36'):Node{return node('text',{text:value,name:value,width:Math.max(size,value.length*size*.62),height:size*1.13,fontSize:size,fontFamily:'Helvetica Neue',transform:at(x,y),style:paint(color)});}
function seedRandom(seed:number){let state=seed>>>0;return()=>{state=(Math.imul(1664525,state)+1013904223)>>>0;return state/4294967296;};}
function stableIds(n:Node){let i=0;function visit(x:Node){for(const child of x.children){child.id=n.id+'-'+(++i);visit(child);}if(x.clip){x.clip.id=n.id+'-'+(++i);visit(x.clip);}}visit(n);return n;}
function group(name:string,w:number,h:number,children:Node[],science:Science):Node{return stableIds(node('group',{name,width:w,height:h,children,science,style:paint('none')}));}
export function validateParameters(p:Parameters){for(const [key,min,max] of [['width',40,2000],['height',40,2000],['spacing',8,120],['thickness',8,100],['count',2,100],['seed',0,2147483647]] as const){if(!Number.isFinite(p[key])||p[key]<min||p[key]>max)throw Error(`${key}: ${min}–${max} 범위의 값을 입력하세요.`);}if(!Number.isInteger(p.count)||!Number.isInteger(p.seed))throw Error('개수와 시드는 정수로 입력하세요.');for(const c of [p.color,p.accent])if(!/^#[a-f\d]{6}$/i.test(c))throw Error('색상은 6자리 HEX로 입력하세요.');}
function brushGeometry(id:BrushId,d:string,p:Parameters){
 const curve=new scope.Path(d);const children:Node[]=[];const length=curve.length;
 try{
  if(!Number.isFinite(length)||length<1||length>12000)throw Error('브러시 경로 길이는 1–12,000이어야 합니다.');
  const position=(s:number,offset=0)=>{const v=curve.getPointAt(Math.min(length,Math.max(0,s)))!,t=curve.getTangentAt(Math.min(length-.00001,Math.max(.00001,s)))!;return {x:v.x-t.y*offset,y:v.y+t.x*offset,t};};
  // Arc-length placement prevents density changes on long/short Bézier segments.
  if(id==='membrane'||id==='beads'){
   const count=Math.min(350,Math.max(2,Math.floor(length/p.spacing)));const step=length/count;
   for(let i=0;i<=(curve.closed?count-1:count);i++){
    const q=position(i*step);if(id==='beads'){children.push(ellipse(q.x,q.y,p.thickness*.42,p.thickness*.42,i%2?p.accent:p.color));continue;}
    // Shrink the bilayer on tight bends instead of crossing adjacent tails.
    const curvature=Math.abs(curve.getCurvatureAt(Math.min(length-.001,Math.max(.001,i*step)))||0),half=Math.min(p.thickness/2,curvature>.001?.65/curvature:p.thickness/2);
    for(const sign of [-1,1]){const h=position(i*step,sign*half),inner=position(i*step,sign*half*.18),r=Math.min(4,step*.24,half*.3);children.push(path(`M ${h.x-q.t.x*r*.5} ${h.y-q.t.y*r*.5} L ${inner.x-q.t.x*r*.5} ${inner.y-q.t.y*r*.5} M ${h.x+q.t.x*r*.5} ${h.y+q.t.y*r*.5} L ${inner.x+q.t.x*r*.5} ${inner.y+q.t.y*r*.5}`,p.color,1.6),ellipse(h.x,h.y,r*2,r*2,p.color));}
   }
  }else{
   const strand=(phase:number,offset=0)=>{const parts:string[]=[];for(let s=0;s<length+4;s+=4){const v=position(Math.min(s,length),offset+Math.sin(Math.min(s,length)/p.spacing*Math.PI/2+phase)*p.thickness/2);parts.push(`${parts.length?'L':'M'} ${v.x} ${v.y}`);}return parts.join(' ');};
   if(id==='fiber'){for(const offset of [-p.thickness/3,0,p.thickness/3])children.push(path(strand(0,offset),p.color,2));}
   else{if(id==='dna'){for(let s=0;s<=length;s+=p.spacing/2){const offset=Math.sin(s/p.spacing*Math.PI/2)*p.thickness/2,a=position(s,offset),b=position(s,-offset);children.push(path(`M ${a.x} ${a.y} L ${b.x} ${b.y}`,p.accent,2));}children.push(path(strand(Math.PI),p.accent,3));}children.push(path(strand(0),p.color,3));if(id==='rna')for(let s=0;s<=length;s+=p.spacing){const q=position(s,Math.sin(s/p.spacing*Math.PI/2)*p.thickness/2);children.push(ellipse(q.x,q.y,6,6,p.accent));}}
  }
  return {children,bounds:curve.bounds.clone()};
 }finally{curve.remove();}
}
export function generate(spec:Extract<Science,{type:'generator'|'brush'}>):Node{
 const p=spec.params;validateParameters(p);const {width:w,height:h,color:c,accent:a}=p;let children:Node[]=[];
 if(spec.type==='brush'){
  const {children:parts,bounds}=brushGeometry(spec.id,spec.path,p);for(const part of parts){part.transform.x-=bounds.center.x;part.transform.y-=bounds.center.y;}
  return group(brushes[spec.id]+' 브러시',bounds.width+p.thickness+10,bounds.height+p.thickness+10,parts,spec);
 }
 switch(spec.id){
  case 'membrane':children=brushGeometry('membrane',`M ${-w/2+8} 0 L ${w/2-8} 0`,p).children;break;
  case 'dna':case 'rna':children=brushGeometry(spec.id,`M ${-w/2+8} 0 L ${w/2-8} 0`,p).children;break;
  case 'vesicle':{if(Math.min(w,h)<=p.thickness+32)throw Error('소포 너비와 높이는 모티프 두께보다 32 이상 커야 합니다.');const r=Math.min(w,h)/2-p.thickness/2-8;children=brushGeometry('membrane',`M ${-r} 0 A ${r} ${r} 0 1 0 ${r} 0 A ${r} ${r} 0 1 0 ${-r} 0 Z`,p).children;break;}
  case 'cell':children=[ellipse(0,0,w-8,h-8,'#edf5ef',c,3),ellipse(-w*.1,h*.04,w*.38,h*.4,'#dbe7f1',c,2),ellipse(-w*.08,h*.05,w*.12,h*.13,a)];for(let i=0;i<6;i++){const t=i*Math.PI/3;children.push(ellipse(Math.cos(t)*w*.32,Math.sin(t)*h*.32,22,12,a,c,1));}break;
  case 'receptor':children=[path(`M ${-w*.25} ${-h*.4} L ${-w*.15} ${-h*.15} L ${w*.15} ${-h*.15} L ${w*.25} ${-h*.4}`,c,10),rect(0,0,w*.16,h*.5,c),path(`M 0 ${h*.2} L ${w*.15} ${h*.4}`,a,9)];break;
  case 'antibody':children=[path(`M 0 ${h*.45} L 0 ${-h*.03} L ${-w*.3} ${-h*.4} M 0 ${-h*.03} L ${w*.3} ${-h*.4}`,c,12),path(`M ${-w*.36} ${-h*.32} L ${-w*.21} ${-h*.12} M ${w*.36} ${-h*.32} L ${w*.21} ${-h*.12}`,a,9)];break;
  case 'particles':{const random=seedRandom(p.seed);for(let i=0;i<p.count;i++){const angle=random()*Math.PI*2,r=Math.sqrt(random())*.4;children.push(ellipse(Math.cos(angle)*w*r,Math.sin(angle)*h*r,p.thickness*.6,p.thickness*.6,i%3?c:a,'#ffffff',1));}break;}
  case 'hydrogel':{const random=seedRandom(p.seed),rows=Math.max(2,Math.round(Math.sqrt(p.count))),cols=rows;const points=Array.from({length:rows+1},(_,y)=>Array.from({length:cols+1},(_,x)=>({x:-w*.42+x*w*.84/cols+(random()-.5)*10,y:-h*.42+y*h*.84/rows+(random()-.5)*10})));points.forEach((row,y)=>row.forEach((q,x)=>{for(const b of [row[x+1],points[y+1]?.[x]])if(b)children.push(path(`M ${q.x} ${q.y} Q ${(q.x+b.x)/2+10} ${(q.y+b.y)/2-10} ${b.x} ${b.y}`,c,2));children.push(ellipse(q.x,q.y,7,7,a));}));break;}
  case 'tube':children=[path(`M ${-w*.18} ${-h*.35} L ${-w*.18} ${h*.3} Q 0 ${h*.65} ${w*.18} ${h*.3} L ${w*.18} ${-h*.35} Z`,c,2,'#f2f7f5'),path(`M ${-w*.16} 0 L ${-w*.16} ${h*.28} Q 0 ${h*.58} ${w*.16} ${h*.28} L ${w*.16} 0 Z`,'none',0,a),rect(0,-h*.4,w*.46,h*.1,c)];for(let i=0;i<4;i++)children.push(path(`M ${w*.07} ${-h*.23+i*h*.12} L ${w*.16} ${-h*.23+i*h*.12}`,c,1.5));break;
 }
 return group(generators[spec.id],w,['membrane','dna','rna'].includes(spec.id)?Math.max(h,p.thickness+12):h,children,spec);
}
export function table(spec:Extract<Science,{type:'table'}>):Node{
 const {cells,cellWidth:w,rowHeight:h,fontSize,color,accent}=spec,cols=cells[0]?.length??0;
 if(!cells.length||cells.length>20||!cols||cols>12||cells.some(r=>r.length!==cols||r.some(v=>v.length>200)))throw Error('표는 같은 열 수를 가진 1–20행, 1–12열이어야 합니다. 셀당 200자까지 가능합니다.');
 if(w<40||w>500||h<24||h>200||fontSize<8||fontSize>60)throw Error('셀 너비 40–500, 높이 24–200, 글자 8–60 범위를 사용하세요.');
 const children:Node[]=[];cells.forEach((row,y)=>row.forEach((value,x)=>{const cx=(x-(cols-1)/2)*w,cy=(y-(cells.length-1)/2)*h;children.push(rect(cx,cy,w,h,y===0&&spec.header?accent:'#ffffff',color,1));const label=text(value,cx,cy,fontSize,color);label.width=w-12;label.textAlign='center';label.fontWeight=y===0&&spec.header?'bold':'normal';label.clip=rect(0,0,w-10,h-4,'#000000');children.push(label);}));
 return group('표',cols*w,cells.length*h,children,spec);
}
function panelLabel(index:number):string{let result='';for(let value=index+1;value>0;value=Math.floor((value-1)/26))result=String.fromCharCode(65+(value-1)%26)+result;return result;}
export function panels(spec:Extract<Science,{type:'panels'}>):Node{
 const {rows,columns:cols,panelWidth:w,panelHeight:h,gap,color}=spec;if(!Number.isInteger(rows)||!Number.isInteger(cols)||rows<1||cols<1||rows*cols>12||w<100||w>1500||h<100||h>1500||gap<0||gap>200||! /^[A-Z]$/.test(spec.startLabel))throw Error('패널은 최대 12개, 크기는 100–1500, 여백은 0–200입니다. 시작 라벨은 A–Z입니다.');
 const width=cols*w+(cols-1)*gap,height=rows*h+(rows-1)*gap,children:Node[]=[];
 for(let y=0;y<rows;y++)for(let x=0;x<cols;x++){const cx=-width/2+w/2+x*(w+gap),cy=-height/2+h/2+y*(h+gap);children.push(rect(cx,cy,w,h,'none','#b7c9c0',1));const label=text(panelLabel(spec.startLabel.charCodeAt(0)-65+y*cols+x),cx-w/2+24,cy-h/2+24,26,color);label.fontWeight='bold';children.push(label);}
 return group('그림 패널',width,height,children,spec);
}
export function inset(source:Node,spec:Extract<Science,{type:'inset'}>,id?:string):Node{
 if(walk([source]).some(n=>n.science?.type==='inset'))throw Error('확대 삽화가 포함된 객체는 확대할 수 없습니다. 원본 객체를 선택하세요.');
 if(spec.size<80||spec.size>1000||spec.span<.1||spec.span>1||spec.centerX<0||spec.centerX>1||spec.centerY<0||spec.centerY>1)throw Error('확대 영역 또는 크기가 범위를 벗어났습니다.');
 const clone=structuredClone(source);clone.transform=transform();clone.visible=true;clone.locked=false;for(const n of walk([clone])){n.science=null;if(n.link){n.link.start=null;n.link.end=null;}}
 const scale=spec.size/(Math.max(source.width,source.height,1)*spec.span);clone.transform={...transform(),scaleX:scale,scaleY:scale,x:(.5-spec.centerX)*source.width*scale,y:(.5-spec.centerY)*source.height*scale};
 const frame=spec.shape==='circle'?ellipse(0,0,spec.size,spec.size,'none',spec.color,2):rect(0,0,spec.size,spec.size,'none',spec.color,2);
 const content=node('group',{width:spec.size,height:spec.size,children:[clone],clip:spec.shape==='circle'?ellipse(0,0,spec.size-2,spec.size-2,'#000000'):rect(0,0,spec.size-2,spec.size-2,'#000000'),style:paint('none')});
 const result=group('확대 삽화',spec.size,spec.size,[content,frame],spec);if(id){result.id=id;stableIds(result);}return result;
}
/** Source movement does not change a local crop; edits to the source geometry do. */
export function refreshInsets(nodes:Node[]):string[]{
 const all=walk(nodes),byId=new Map(all.map(n=>[n.id,n])),changed:string[]=[];
 for(const n of all){const s=n.science;if(s?.type!=='inset'||!s.live)continue;const source=s.sourceId?byId.get(s.sourceId):undefined;
  if(!source||walk([source]).some(x=>x.science?.type==='inset')){s.live=false;s.sourceId=null;changed.push(n.id);continue;}
  const generated=inset(source,s,n.id);if(JSON.stringify(n.children)!==JSON.stringify(generated.children)){n.children=generated.children;changed.push(n.id);}
 }
 return changed;
}
export function scienceName(s:Science):string{return s.type==='generator'?generators[s.id]:s.type==='brush'?brushes[s.id]+' 브러시':({equation:'LaTeX 수식',table:'표',panels:'그림 패널',inset:'확대 삽화'} as const)[s.type];}
