import test from 'node:test';
import assert from 'node:assert/strict';
import {once, EventEmitter} from 'node:events';
import {PassThrough} from 'node:stream';
import {createApp} from '../index.js';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');

async function host(t, options={}) {
 const server=createApp(options).listen(0,'127.0.0.1');await once(server,'listening');
 t.after(()=>new Promise(resolve=>server.close(resolve)));
 return `http://127.0.0.1:${server.address().port}`;
}
test('graph, string gid search, CSV and missing node',async t=>{
 const base=await host(t);const graph=await (await fetch(base+'/api/graph')).json();
 assert.equal(graph.nodes.length,2248);assert.equal(graph.edges.length,3119);
 const id=graph.nodes[0].gid;assert.equal(typeof id,'string');
 const node=await (await fetch(base+'/api/nodes/'+id)).json();assert.equal(node.gid,id);assert.ok(node.evidence);
 assert.ok(node.edges.every(e=>e.from_gid===id||e.to_gid===id));
 assert.equal((await fetch(base+'/api/nodes/not-a-gid')).status,404);
 const csv=await (await fetch(base+'/api/download/nodes_roles.csv')).text();assert.match(csv,/gid,role,role_score,cluster_id,priority_score,evidence/);
 assert.equal((await fetch(base+'/api/download/.env')).status,404);
});
test('mutation protections, concurrent run and failed child preserve snapshot',async t=>{
 let child;const fake=()=>{child=new EventEmitter();child.stdout=new PassThrough();child.stderr=new PassThrough();child.kill=()=>{};return child;};
 const base=await host(t,{spawnProcess:fake});
 assert.equal((await fetch(base+'/api/pipeline',{method:'POST'})).status,403);
 const {token}=await (await fetch(base+'/api/session')).json();
 const options={method:'POST',headers:{'X-Run-Token':token}};
 assert.equal((await fetch(base+'/api/pipeline',{...options,headers:{...options.headers,Origin:'https://elsewhere.invalid'}})).status,403);
 assert.equal((await fetch(base+'/api/pipeline',options)).status,202);
 assert.equal((await fetch(base+'/api/pipeline',options)).status,409);
 child.emit('close',1);
 assert.equal((await (await fetch(base+'/api/pipeline/status')).json()).status,'failed');
 assert.equal((await (await fetch(base+'/api/graph')).json()).nodes.length,2248);
});
test('public mode disables rerun',async t=>{
 const base=await host(t,{allowRun:false});assert.equal((await fetch(base+'/api/pipeline',{method:'POST'})).status,403);
 assert.equal((await (await fetch(base+'/api/session')).json()).canRun,false);
});
test('upload validates names and corrupt parquet without replacing the original dataset',async t=>{
 const base=await host(t);const {token}=await (await fetch(base+'/api/session')).json();
 const options=files=>({method:'POST',headers:{'X-Run-Token':token,'Content-Type':'application/json'},body:JSON.stringify({files})});
 assert.equal((await fetch(base+'/api/upload',options([]))).status,400);
 const files=['nodes.parquet','edges.parquet','transactions.parquet'].map(name=>({name,data:Buffer.from('not parquet').toString('base64')}));
 const response=await fetch(base+'/api/upload',options(files));assert.equal(response.status,422);
 assert.equal((await (await fetch(base+'/api/graph')).json()).nodes.length,2248);
});
test('real parquet upload is memory-only and returns matching CSV and signals',async t=>{
 const snapshot=()=>Object.fromEntries(['python','data'].flatMap(directory=>fs.readdirSync(path.join(root,directory),{recursive:true,withFileTypes:true})
   .filter(e=>e.isFile()).map(e=>{const full=path.join(e.parentPath,e.name);return [full,crypto.createHash('sha256').update(fs.readFileSync(full)).digest('hex')];})));
 const base=await host(t);const {token}=await (await fetch(base+'/api/session')).json();
 const files=['nodes.parquet','edges.parquet','transactions.parquet'].map(name=>({name,data:fs.readFileSync(path.join(root,'data/raw',name)).toString('base64')}));
 const before=snapshot();
 const response=await fetch(base+'/api/upload',{method:'POST',headers:{'X-Run-Token':token,'Content-Type':'application/json'},body:JSON.stringify({files})});
 const result=await response.json();assert.equal(response.status,200,JSON.stringify(result).slice(0,400));
 assert.equal(result.graph.nodes.length,2248);assert.equal(result.signals.n_tests,540);
 assert.ok(result.graph.nodes.every(n=>typeof n.gid==='string'));
 const original=await (await fetch(base+'/api/dataset')).json();
 assert.deepEqual(result.graph.nodes.map(n=>[n.gid,n.cluster_id,n.seed_ancestors_4,n.matched_1_2_days_kzt,n.max_daily_payers,n.cycle_size,n.activity]),
                  original.graph.nodes.map(n=>[n.gid,n.cluster_id,n.seed_ancestors_4,n.matched_1_2_days_kzt,n.max_daily_payers,n.cycle_size,n.activity]));
 assert.equal(Math.min(...result.clusters.map(c=>c.cluster_id)),1);
 assert.equal(Object.keys(result.csvs).length,3);
 assert.equal(result.csvs['nodes_roles.csv'].trim().split('\n').length,2249);
 assert.deepEqual(snapshot(),before,'Uploaded analysis wrote to disk');
 assert.equal((await (await fetch(base+'/api/dataset')).json()).graph.report.source,undefined);
});
