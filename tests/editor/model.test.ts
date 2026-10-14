import {describe,expect,test} from 'bun:test';
import {History,node,remap,detachMissing} from '../../src/editor/model';
import {Path,Rect,Group,util} from 'fabric';
import {toNode,objectTransform,connectionPath} from '../../src/editor/adapter';
import {Point} from 'fabric';
describe('document commands',()=>{
 test('undo/redo branch keeps transactional snapshots',()=>{const h=new History('a');h.push('b');h.push('b');h.push('c');expect(h.undo()).toBe('b');expect(h.undo()).toBe('a');expect(h.redo()).toBe('b');h.push('d');expect(h.redo()).toBeNull();expect(h.undo()).toBe('b');});
 test('copy remaps nested nodes, masks and internal connections',()=>{const a=node('rect'),b=node('ellipse'),c=node('connector',{link:{start:{nodeId:a.id,x:1,y:.5},end:{nodeId:b.id,x:0,y:.5},mode:'curve',startHead:'none',endHead:'arrow'}});a.clip=node('ellipse');const group=node('group',{children:[a,b,c]});const copy=remap([group])[0]!;expect(copy.id).not.toBe(group.id);expect(copy.children[2]?.link?.start?.nodeId).toBe(copy.children[0]?.id);expect(copy.children[0]?.clip?.id).not.toBe(a.clip.id);});
 test('deleted endpoints detach without deleting the connector',()=>{const c=node('connector',{link:{start:{nodeId:'missing',x:0,y:.5},end:null,mode:'straight',startHead:'none',endHead:'arrow'}});detachMissing([c]);expect(c.link?.start).toBeNull();});
 test('transform roundtrip preserves reflected rotated geometry',()=>{const r=new Rect({left:320,top:250,width:100,height:70,angle:32,scaleX:1.8,scaleY:.7,flipX:true});const t=objectTransform(r);const rebuilt=new Rect({left:t.x,top:t.y,width:100,height:70,angle:t.angle,scaleX:t.scaleX,scaleY:t.scaleY,flipX:t.flipX,flipY:t.flipY,skewX:t.skewX});r.calcOwnMatrix().forEach((x,i)=>expect(rebuilt.calcOwnMatrix()[i]!).toBeCloseTo(x,6));});
 test('path offsets and group local coordinates are serialized',()=>{const p=new Path('M 10 20 C 40 0 70 100 100 80');p.bio=node('path');const r=new Rect({left:400,top:200,width:100,height:70});r.bio=node('rect');const g=new Group([p,r]);g.bio=node('group');const n=toNode(g);expect(n.children).toHaveLength(2);expect(n.children[0]?.path).toContain('C');expect(n.children[0]?.transform.x).toBeCloseTo(p.left);expect(connectionPath(new Point(0,0),new Point(100,50),'curve')).toContain('C 50');});
});
