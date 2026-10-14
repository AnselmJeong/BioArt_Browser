import type { Science } from './science';
/** Portable document schema. Fabric objects are adapters, never the saved document. */
export type Transform = {x:number;y:number;scaleX:number;scaleY:number;angle:number;skewX:number;skewY:number;flipX:boolean;flipY:boolean};
export type Gradient = {type:'linear'|'radial';units:'pixels'|'percentage';coords:Record<string,number>;stops:{offset:number;color:string;opacity:number}[];offsetX:number;offsetY:number;matrix:number[]|null};
export type Style = {fill:string|Gradient;stroke:string;strokeWidth:number;opacity:number;dash:number[];lineCap:'butt'|'round'|'square';lineJoin:'miter'|'round'|'bevel';fillRule:'nonzero'|'evenodd'};
export type Anchor = {nodeId:string;x:number;y:number};
export type Link = {start:Anchor|null;end:Anchor|null;mode:'straight'|'curve'|'elbow';startHead:'none'|'arrow'|'bar';endHead:'none'|'arrow'|'bar'};
export type Kind = 'rect'|'ellipse'|'path'|'text'|'asset'|'image'|'group'|'connector';
export interface Node {
 science:Science|null;id:string;kind:Kind;name:string;transform:Transform;width:number;height:number;style:Style;visible:boolean;locked:boolean;
 radius:number;path:string;pathOffset:number[];text:string;fontSize:number;fontFamily:string;fontWeight:'normal'|'bold';fontStyle:'normal'|'italic';textAlign:'left'|'center'|'right';lineHeight:number;
 fileId:string|null;sha256:string|null;imagePath:string|null;sourceFileIds:string[];children:Node[];clip:Node|null;link:Link|null;
}
export interface FigureDocument {schemaVersion:1;id:string;revision:number;title:string;artboard:{width:number;height:number;background:string};nodes:Node[];sourceSceneId:string|null;updatedAt:string}
export interface AssetData {fileId:string;sha256:string;format:string;title:string;url:string;svg:string|null}
export type API = <T>(path:string,body?:unknown)=>Promise<T>;
export const uid=()=> 'n-'+crypto.randomUUID().replaceAll('-','').slice(0,12);
export const transform=():Transform=>({x:0,y:0,scaleX:1,scaleY:1,angle:0,skewX:0,skewY:0,flipX:false,flipY:false});
export const style=():Style=>({fill:'#b8d9c7',stroke:'#276a57',strokeWidth:2,opacity:1,dash:[],lineCap:'round',lineJoin:'round',fillRule:'nonzero'});
export function node(kind:Kind,overrides:Partial<Node>={}):Node {
 return {science:null,id:uid(),kind,name:kind,transform:transform(),width:160,height:100,style:style(),visible:true,locked:false,radius:0,path:'',pathOffset:[0,0],text:'설명',fontSize:28,fontFamily:'Helvetica Neue',fontWeight:'normal',fontStyle:'normal',textAlign:'left',lineHeight:1.16,fileId:null,sha256:null,imagePath:null,sourceFileIds:[],children:[],clip:null,link:null,...overrides};
}
export function walk(nodes:Node[]):Node[]{return nodes.flatMap(n=>[n,...walk(n.children)]);}
export function remap(nodes:Node[]):Node[]{
 const out=structuredClone(nodes),ids=new Map<string,string>();
 function visit(n:Node){const old=n.id;n.id=uid();ids.set(old,n.id);n.children.forEach(visit);if(n.clip)visit(n.clip);}
 out.forEach(visit);
 for(const n of walk(out)){for(const a of [n.link?.start,n.link?.end])if(a)a.nodeId=ids.get(a.nodeId)??a.nodeId;if(n.science?.type==='inset'&&n.science.sourceId)n.science.sourceId=ids.get(n.science.sourceId)??n.science.sourceId;}
 return out;
}
export function detachMissing(nodes:Node[]):void {
 const ids=new Set(walk(nodes).map(n=>n.id));
 for(const n of walk(nodes))if(n.link){if(n.link.start&&!ids.has(n.link.start.nodeId))n.link.start=null;if(n.link.end&&!ids.has(n.link.end.nodeId))n.link.end=null;}
}
export class History {
 private past:string[]=[];private future:string[]=[];private current:string;
 constructor(nodes:string){this.current=nodes;}
 push(next:string){if(next===this.current)return false;this.past.push(this.current);if(this.past.length>80)this.past.shift();this.current=next;this.future=[];return true;}
 undo(){const previous=this.past.pop();if(previous===undefined)return null;this.future.push(this.current);this.current=previous;return previous;}
 redo(){const next=this.future.pop();if(next===undefined)return null;this.past.push(this.current);this.current=next;return next;}
 get canUndo(){return this.past.length>0;}get canRedo(){return this.future.length>0;}
}
