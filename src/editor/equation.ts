import { mathjax } from 'mathjax-full/js/mathjax.js';
import { TeX } from 'mathjax-full/js/input/tex.js';
import { SVG } from 'mathjax-full/js/output/svg.js';
import { liteAdaptor } from 'mathjax-full/js/adaptors/liteAdaptor.js';
import { RegisterHTMLHandler } from 'mathjax-full/js/handlers/html.js';
import 'mathjax-full/js/input/tex/ams/AmsConfiguration.js';
import { Group, Path, Rect, loadSVGFromString } from 'fabric';
import { toNode } from './adapter';
import { node, transform } from './model';
import type { Science } from './science';
const adaptor=liteAdaptor();RegisterHTMLHandler(adaptor);
/** Only base/AMS are installed: no URL, HTML, require, autoload, or user macros. */
export function equationSVG(latex:string,size:number,color:string):string{
 if(!latex.trim()||latex.length>2000||size<8||size>160||!/^#[a-f\d]{6}$/i.test(color))throw Error('수식은 1–2,000자, 크기는 8–160이어야 합니다.');
 const tex=new TeX({packages:['base','ams'],maxBuffer:4096,maxMacros:1000,formatError:(_jax:unknown,error:{message:string})=>{throw Error('수식 오류: '+error.message);}});
 const doc=mathjax.document('',{InputJax:tex,OutputJax:new SVG({fontCache:'none'})});
 const result=adaptor.outerHTML(doc.convert(latex,{display:true}));
 const start=result.indexOf('<svg'),end=result.indexOf('</svg>');if(start<0||end<0)throw Error('수식 렌더링에 실패했습니다.');
 let svg=result.slice(start,end+6).replaceAll('currentColor',color);
 const box=/viewBox="([^"]+)"/.exec(svg)?.[1]?.split(' ').map(Number);if(!box||box.length!==4)throw Error('수식 크기를 읽을 수 없습니다.');
 svg=svg.replace(/\swidth="[^"]+"/,` width="${box[2]!*size/1000}"`).replace(/\sheight="[^"]+"/,` height="${box[3]!*size/1000}"`);
 return svg;
}
export async function equation(spec:Extract<Science,{type:'equation'}>){
 const parsed=await loadSVGFromString(equationSVG(spec.latex,spec.size,spec.color));
 const objects=parsed.objects.filter(o=>o instanceof Path||o instanceof Rect);
 if(!objects.length)throw Error('수식에 렌더링 가능한 기호가 없습니다.');
 for(const o of objects)o.bio=node(o instanceof Rect?'rect':'path',{name:'수식 기호'});
 const g=new Group(objects);g.bio=node('group',{name:'수식 · '+spec.latex.slice(0,50),science:spec});const result=toNode(g);result.transform=transform();return result;
}
