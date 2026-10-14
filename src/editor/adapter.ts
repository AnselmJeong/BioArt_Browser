import { ActiveSelection, Canvas, StaticCanvas, Color, Circle, Ellipse, FabricImage, FabricObject, FabricText, Gradient as FabricGradient, Group, IText, Line, Path, Point, Polygon, Polyline, Rect, FixedLayout, LayoutManager, util, loadSVGFromString } from 'fabric';
import type { TMat2D } from 'fabric';
import { node, uid } from './model';
import type { API, AssetData, Gradient, Node, Transform, Link } from './model';

declare module 'fabric' { interface FabricObject { bio?:Node; helper?:boolean; sourceMissing?:boolean } }
FabricObject.ownDefaults.originX='center';FabricObject.ownDefaults.originY='center';
FabricObject.ownDefaults.cornerColor='#276a57';FabricObject.ownDefaults.cornerStrokeColor='#ffffff';
FabricObject.ownDefaults.cornerSize=9;FabricObject.ownDefaults.transparentCorners=false;FabricObject.ownDefaults.borderColor='#276a57';

export class SourceImage extends FabricImage {
 override _render(ctx:CanvasRenderingContext2D){
  const el=this.getElement();const size=this.getOriginalSize();
  const fit=Math.min(this.width/size.width,this.height/size.height),w=size.width*fit,h=size.height*fit;
  ctx.drawImage(el,-w/2,-h/2,w,h);
 }
}
export class ConnectorPath extends Path {
 override _render(ctx:CanvasRenderingContext2D){
  super._render(ctx);if(!this.bio?.link)return;
  const commands=this.path,first=commands[0],last=commands.at(-1);if(!first||!last)return;
  const start=new Point(Number(first[1]),Number(first[2]));
  const end=new Point(Number(last.at(-2)),Number(last.at(-1)));
  const next=commands[1];if(!next)return;
  const before=last[0]==='C'?new Point(last[3],last[4]):last[0]==='Q'?new Point(last[1],last[2]):new Point(Number(commands.at(-2)?.at(-2)??start.x),Number(commands.at(-2)?.at(-1)??start.y));
  const after=new Point(Number(next[1]),Number(next[2]));
  const head=(p:Point,angle:number,kind:string)=>{if(kind==='none')return;ctx.save();ctx.translate(p.x-this.pathOffset.x,p.y-this.pathOffset.y);ctx.rotate(angle);const s=Math.max(1,this.strokeWidth);ctx.scale(s,s);ctx.fillStyle=typeof this.stroke==='string'?this.stroke:'#276a57';ctx.strokeStyle=ctx.fillStyle;ctx.lineWidth=2;ctx.beginPath();if(kind==='bar'){ctx.moveTo(0,-5);ctx.lineTo(0,5);ctx.stroke();}else{ctx.moveTo(1,0);ctx.lineTo(-7,-4);ctx.lineTo(-7,4);ctx.closePath();ctx.fill();}ctx.restore();};
  head(start,Math.atan2(start.y-after.y,start.x-after.x),this.bio.link.startHead);
  head(end,Math.atan2(end.y-before.y,end.x-before.x),this.bio.link.endHead);
 }
}
export const assets=new Map<string,AssetData>();
export async function getAsset(api:API,id:string){let a=assets.get(id);if(!a){a=await api<AssetData>('/api/documents/assets/'+id);assets.set(id,a);}return a;}
function paint(value:Node['style']['fill']):FabricObject['fill']{
 if(typeof value==='string')return value==='none'?null:value;
 const props={gradientUnits:value.units,coords:value.coords,colorStops:value.stops.map(s=>({offset:s.offset,color:new Color(s.color).setAlpha(s.opacity).toRgba()})),offsetX:value.offsetX,offsetY:value.offsetY,...(value.matrix?{gradientTransform:value.matrix as TMat2D}:{})};
 return value.type==='linear'?new FabricGradient<'linear'>({...props,type:'linear'}):new FabricGradient<'radial'>({...props,type:'radial'});
}
function options(n:Node){const t=n.transform,s=n.style;return {left:t.x,top:t.y,originX:'center' as const,originY:'center' as const,scaleX:t.scaleX,scaleY:t.scaleY,angle:t.angle,skewX:t.skewX,skewY:t.skewY,flipX:t.flipX,flipY:t.flipY,fill:paint(s.fill),stroke:s.stroke==='none'?null:s.stroke,strokeWidth:s.strokeWidth,opacity:s.opacity,strokeDashArray:s.dash,strokeLineCap:s.lineCap,strokeLineJoin:s.lineJoin,fillRule:s.fillRule,visible:n.visible,selectable:!n.locked,evented:!n.locked,objectCaching:n.kind==='asset'||n.kind==='group'};}
export async function fromNode(n:Node,api:API):Promise<FabricObject>{
 const opt=options(n);let o:FabricObject;
 if(n.kind==='group'){
  const children=await Promise.all(n.children.map(c=>fromNode(c,api)));
  o=new Group(children,{...opt,width:n.width,height:n.height,layoutManager:new LayoutManager(new FixedLayout()),subTargetCheck:true});
  children.forEach((c,i)=>{const child=n.children[i];if(child)c.set(options(child));});
 }else if(n.kind==='rect')o=new Rect({...opt,width:n.width,height:n.height,rx:n.radius,ry:n.radius});
 else if(n.kind==='ellipse')o=new Ellipse({...opt,rx:n.width/2,ry:n.height/2});
 else if(n.kind==='path'||n.kind==='connector'){
  o=n.kind==='connector'?new ConnectorPath(n.path,opt):new Path(n.path,opt);
  // The offset is part of the canonical geometry, including legacy zero-offset paths.
  if(o instanceof Path){o.pathOffset=new Point(n.pathOffset[0]??0,n.pathOffset[1]??0);o.set({width:n.width,height:n.height});}
 }else if(n.kind==='text')o=new IText(n.text,{...opt,fontSize:n.fontSize,fontFamily:n.fontFamily,fontWeight:n.fontWeight,fontStyle:n.fontStyle,textAlign:n.textAlign,lineHeight:n.lineHeight});
 else{
  try{
   const url=n.fileId?(await getAsset(api,n.fileId)).url:await api<{url:string}>('/api/documents/generated-image?path='+encodeURIComponent(n.imagePath??'')).then(v=>v.url);
   const img=await util.loadImage(url);o=new SourceImage(img,{...opt,width:n.width,height:n.height});
  }catch{
   o=new Rect({...opt,width:n.width,height:n.height,fill:'#f9e8df',stroke:'#b96542',strokeDashArray:[8,6]});
   o.sourceMissing=true;
   // Keep the source node's type and fingerprint so reconnect never discards it.
  }
 }
 o.bio=structuredClone(n);
 if(n.clip)o.clipPath=await fromNode(n.clip,api);
 o.setCoords();return o;
}
function fillValue(o:FabricObject):string|Gradient{
 if(o.fill instanceof FabricGradient)return {type:o.fill.type,units:o.fill.gradientUnits,coords:{...o.fill.coords},stops:o.fill.colorStops.map(s=>({offset:s.offset,color:s.color,opacity:1})),offsetX:o.fill.offsetX,offsetY:o.fill.offsetY,matrix:o.fill.gradientTransform?[...o.fill.gradientTransform]:null};
 if(typeof o.fill==='string')return o.fill||'none';return 'none';
}
export function objectTransform(o:FabricObject,world=false):Transform{
 const matrix=world?o.calcTransformMatrix():o.calcOwnMatrix(),v=util.qrDecompose(matrix);
 return {x:v.translateX,y:v.translateY,scaleX:Math.max(.0001,Math.abs(v.scaleX)),scaleY:Math.max(.0001,Math.abs(v.scaleY)),angle:v.angle,skewX:v.skewX,skewY:0,flipX:v.scaleX<0,flipY:v.scaleY<0};
}
export function toNode(o:FabricObject,world=false):Node{
 const old=o.bio;
 let kind=old?.kind??(o instanceof Group?'group':o instanceof IText?'text':o instanceof Rect?'rect':o instanceof Ellipse||o instanceof Circle?'ellipse':'path');
 const n=node(kind,{...old,id:old?.id??uid(),transform:objectTransform(o,world),width:o.width,height:o.height,visible:o.visible,locked:old?.locked??!o.selectable});
 n.style={fill:fillValue(o),stroke:typeof o.stroke==='string'?o.stroke:'none',strokeWidth:o.strokeWidth,opacity:o.opacity,dash:o.strokeDashArray??[],lineCap:o.strokeLineCap,lineJoin:o.strokeLineJoin,fillRule:o.fillRule};
 if(o.sourceMissing&&old)n.style={...structuredClone(old.style),opacity:o.opacity};
 if(o instanceof Group)n.children=o.getObjects().filter(c=>!c.helper).map(c=>toNode(c));
 if(o instanceof Path){n.path=util.joinPath(o.path);n.pathOffset=[o.pathOffset.x,o.pathOffset.y];}
 if(o instanceof Rect)n.radius=o.rx;
 if(o instanceof IText){n.text=o.text;n.fontSize=o.fontSize;n.fontFamily=o.fontFamily;n.fontWeight=o.fontWeight==='bold'||Number(o.fontWeight)>=600?'bold':'normal';n.fontStyle=o.fontStyle==='italic'?'italic':'normal';n.textAlign=o.textAlign==='center'?'center':o.textAlign==='right'?'right':'left';n.lineHeight=o.lineHeight;}
 if(o.clipPath instanceof FabricObject)n.clip=toNode(o.clipPath);else n.clip=null;
 return n;
}
export function serialize(canvas:Canvas):Node[]{
 return canvas.getObjects().filter(o=>!o.helper).map(o=>toNode(o,!!o.group));
}
export function allObjects(canvas:Canvas):FabricObject[]{
 const visit=(o:FabricObject):FabricObject[]=>[o,...(o instanceof Group?o.getObjects().flatMap(visit):[])];
 return canvas.getObjects().filter(o=>!o.helper).flatMap(visit);
}
export function anchorPoint(o:FabricObject,x=.5,y=.5){return util.transformPoint(new Point((x-.5)*o.width,(y-.5)*o.height),o.calcTransformMatrix());}
export function updateConnections(canvas:Canvas){
 const objects=allObjects(canvas),ids=new Map(objects.map(o=>[o.bio?.id,o]));
 for(const o of objects){
  if(!(o instanceof ConnectorPath)||!o.bio?.link)continue;
  const link=o.bio.link;
  const current=o.path,first=current[0],last=current.at(-1);if(!first||!last)continue;
  const mat=o.calcTransformMatrix();
  let start=util.transformPoint(new Point(Number(first[1])-o.pathOffset.x,Number(first[2])-o.pathOffset.y),mat);
  let end=util.transformPoint(new Point(Number(last.at(-2))-o.pathOffset.x,Number(last.at(-1))-o.pathOffset.y),mat);
  const a=link.start?ids.get(link.start.nodeId):null,b=link.end?ids.get(link.end.nodeId):null;
  if(a&&link.start)start=anchorPoint(a,link.start.x,link.start.y);
  if(b&&link.end)end=anchorPoint(b,link.end.x,link.end.y);
  // Connectors inside groups use local space; targets may live in other groups.
  if(o.group){const inv=util.invertTransform(o.group.calcTransformMatrix());start=util.transformPoint(start,inv);end=util.transformPoint(end,inv);}
  const d=connectionPath(start,end,link.mode);
  o._setPath(d);o.set({left:o.pathOffset.x,top:o.pathOffset.y,scaleX:1,scaleY:1,angle:0,skewX:0,skewY:0,flipX:false,flipY:false});o.dirty=true;o.setCoords();
 }
}
export function connectionPath(a:Point,b:Point,mode:Link['mode']){
 const m=(a.x+b.x)/2;
 return mode==='curve'?`M ${a.x} ${a.y} C ${m} ${a.y} ${m} ${b.y} ${b.x} ${b.y}`:mode==='elbow'?`M ${a.x} ${a.y} L ${m} ${a.y} L ${m} ${b.y} L ${b.x} ${b.y}`:`M ${a.x} ${a.y} L ${b.x} ${b.y}`;
}
export async function editableSVG(svg:string,source:Node):Promise<FabricObject>{
 const sourceTree=new DOMParser().parseFromString(svg,'image/svg+xml');
 if(sourceTree.querySelector('filter,mask,image,foreignObject,[filter],[mask]'))throw new Error('이 SVG에는 경로 변환에서 보존할 수 없는 효과가 있습니다. 원본 배치를 유지하세요.');
 const parsed=await loadSVGFromString(svg);
 const valid=parsed.objects.filter((o):o is FabricObject=>!!o);
 if(!valid.length)throw new Error('편집 가능한 SVG 요소가 없습니다.');
 function normalize(o:FabricObject):FabricObject{
  if(o instanceof FabricText && !(o instanceof IText)){const text=new IText(o.text,{fill:o.fill,stroke:o.stroke,strokeWidth:o.strokeWidth,fontSize:o.fontSize,fontFamily:o.fontFamily,fontWeight:o.fontWeight,fontStyle:o.fontStyle,textAlign:o.textAlign,lineHeight:o.lineHeight});util.applyTransformToObject(text,o.calcOwnMatrix());o=text;}
  if(o instanceof Group){o.getObjects().forEach(normalize);return o;}
  if(o instanceof Polygon||o instanceof Polyline||o instanceof Line){
   let d:string;
   if(o instanceof Line)d=`M ${o.x1} ${o.y1} L ${o.x2} ${o.y2}`;
   else d=o.points.map((p,i)=>`${i?'L':'M'} ${p.x} ${p.y}`).join(' ')+(o instanceof Polygon?' Z':'');
   const path=new Path(d,{fill:o.fill,stroke:o.stroke,strokeWidth:o.strokeWidth,strokeLineCap:o.strokeLineCap,strokeLineJoin:o.strokeLineJoin,opacity:o.opacity});
   util.applyTransformToObject(path,o.calcOwnMatrix());o=path;
  }
  if(typeof o.fill==='string'&&o.fill.startsWith('url('))throw new Error('SVG 패턴 채움은 원본 배치로 유지하세요.');
  if(!(o instanceof Rect||o instanceof Ellipse||o instanceof Circle||o instanceof Path||o instanceof IText))throw new Error('지원하지 않는 SVG 요소가 있습니다. 원본 배치를 사용하세요.');
  o.bio=node(o instanceof Rect?'rect':o instanceof Ellipse||o instanceof Circle?'ellipse':o instanceof IText?'text':'path',{name:'SVG 요소',sourceFileIds:source.fileId?[source.fileId]:source.sourceFileIds});
  if(o.clipPath instanceof FabricObject)normalize(o.clipPath);
  return o;
 }
 const objects=valid.map(normalize);const group=new Group(objects);
 const rootWidth=parsed.options.width||group.width,rootHeight=parsed.options.height||group.height;
 const center=group.getCenterPoint(),factor=Math.min(source.width/rootWidth,source.height/rootHeight),t=source.transform;
 const sourceMatrix=util.composeMatrix({translateX:t.x,translateY:t.y,angle:t.angle,scaleX:t.scaleX,scaleY:t.scaleY,flipX:t.flipX,flipY:t.flipY,skewX:t.skewX,skewY:t.skewY});
 util.applyTransformToObject(group,util.multiplyTransformMatrices(sourceMatrix,[factor,0,0,factor,(center.x-rootWidth/2)*factor,(center.y-rootHeight/2)*factor]));
 group.bio=node('group',{name:source.name+' · 편집용 복사본',sourceFileIds:source.fileId?[source.fileId]:[]});
 await verifyCopy(svg,source,group);
 return group;
}

async function verifyCopy(svg:string,source:Node,group:Group){
 const surface=new StaticCanvas(document.createElement('canvas'),{width:360,height:360,enableRetinaScaling:false,renderOnAddRemove:false});
 try{
  const img=await util.loadImage('data:image/svg+xml;charset=utf-8,'+encodeURIComponent(svg));
  const original=new SourceImage(img,{...options(source),width:source.width,height:source.height});
  const bounds=original.getBoundingRect();
  for(const zoom of [Math.min(1,320/Math.max(bounds.width,bounds.height)),320/Math.max(bounds.width,bounds.height)]){
  surface.remove(...surface.getObjects());
  surface.setViewportTransform([zoom,0,0,zoom,20-bounds.left*zoom,20-bounds.top*zoom]);
  surface.add(original);surface.renderAll();const a=surface.getContext().getImageData(0,0,360,360).data;
  surface.remove(original);const reconstructed=await fromNode(toNode(group),async()=>{throw Error('Unexpected source in vector copy');});surface.add(reconstructed);surface.renderAll();const b=surface.getContext().getImageData(0,0,360,360).data;
  let ink=0,diff=0;for(let i=0;i<a.length;i+=4){if(a[i+3]!>10||b[i+3]!>10){ink++;if(Math.abs(a[i]!-b[i]!)+Math.abs(a[i+1]!-b[i+1]!)+Math.abs(a[i+2]!-b[i+2]!)+Math.abs(a[i+3]!-b[i+3]!)>100)diff++;}}
  if(ink&&diff/ink>.12)throw Error('이 SVG는 경로로 바꾸면 외형이 달라집니다. 원본 배치를 유지했습니다.');
  }
 }finally{await surface.dispose();}
}
