import paper from 'paper/dist/paper-core';
import { FabricObject, Path, Point, util } from 'fabric';
import { node } from './model';
const scope=new paper.PaperScope();scope.setup(new scope.Size(1,1));
export function booleanPath(objects:FabricObject[],operation:'unite'|'subtract'|'intersect'|'exclude'|'divide'):Path {
 if(objects.length!==2)throw new Error('도형이나 경로를 두 개 선택하세요.');
 const imported=objects.map(o=>scope.project.importSVG(`<svg xmlns="http://www.w3.org/2000/svg">${o.toSVG()}</svg>`,{insert:false,expandShapes:true,applyMatrix:true}));
 function path(item:InstanceType<typeof scope.Item>):InstanceType<typeof scope.PathItem>{
  if(item instanceof scope.PathItem)return item;
  const parts=item.children?.flatMap(child=>{try{return [path(child)];}catch{return [];}})??[];
  if(parts.length===1)return parts[0]!;
  if(parts.length>1){const compound=new scope.CompoundPath({insert:false});for(const part of parts){if(part instanceof scope.Path)compound.addChild(part.clone({insert:false}));else if(part instanceof scope.CompoundPath)for(const child of part.children)compound.addChild(child.clone({insert:false}));}return compound;}
  throw new Error('닫힌 도형 또는 경로만 결합할 수 있습니다.');
 }
 try{
  const a=path(imported[0]!),b=path(imported[1]!);let result:InstanceType<typeof scope.PathItem>|InstanceType<typeof scope.Group>;
  result=a[operation](b,{insert:false});
  const combined=path(result),d=combined.pathData;
  if(!d)throw new Error('결합 결과가 비어 있습니다.');
  const out=new Path(d,{fill:objects[0]!.fill,stroke:objects[0]!.stroke,strokeWidth:objects[0]!.strokeWidth});
  out.bio=node('path',{name:'결합한 경로',sourceFileIds:[...new Set(objects.flatMap(o=>o.bio?.sourceFileIds??[]))]});
  result.remove();return out;
 }finally{imported.forEach(i=>i.remove());}
}
export function simplify(path:Path,tolerance=2):Path{
 const item=new scope.Path(util.joinPath(path.path));item.simplify(tolerance);
 const replacement=new Path(item.pathData,{fill:path.fill,stroke:path.stroke,strokeWidth:path.strokeWidth});
 const diff=replacement.pathOffset.subtract(path.pathOffset);
 const m=path.calcTransformMatrix();m[4]+=m[0]*diff.x+m[2]*diff.y;m[5]+=m[1]*diff.x+m[3]*diff.y;
 util.applyTransformToObject(replacement,m);replacement.bio=structuredClone(path.bio??node('path'));item.remove();return replacement;
}
export function nearestSegment(path:Path,scene:Point){
 const p=util.transformPoint(scene,util.invertTransform(path.calcTransformMatrix())).add(path.pathOffset);
 let best=1,dist=Infinity;path.path.forEach((cmd,i)=>{const x=Number(cmd.at(-2)),y=Number(cmd.at(-1));const d=Math.hypot(x-p.x,y-p.y);if(Number.isFinite(d)&&d<dist){dist=d;best=i;}});return best;
}
