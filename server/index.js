import express from 'express';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import http from 'node:http';
import https from 'node:https';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
if (fs.existsSync(path.join(root, 'server/.env'))) process.loadEnvFile(path.join(root, 'server/.env'));

export function createApp({output = path.join(root, 'data/output'), python = process.env.PYTHON || 'python',
                           allowRun = true, timeout = 300000, spawnProcess = spawn} = {}) {
  const app = express(), token = crypto.randomBytes(24).toString('hex');
  let snapshot, nodes, top, clusters, signals, rules, uploadBusy=false, job = {status: 'idle'};
  function reload(directory = output) {
    const report = JSON.parse(fs.readFileSync(path.join(directory, 'pipeline_validation.json')));
    if (report.status !== 'passed' || !report.stages.includes(6)) throw Error('Нет проверенного результата этапов 1–6');
    const graph = JSON.parse(fs.readFileSync(path.join(directory, 'graph.json')));
    if (graph.nodes.some(n => typeof n.gid !== 'string' || !n.role)) throw Error('Неполный graph.json');
    const nextNodes = new Map(graph.nodes.map(n => [n.gid, n]));
    if (nextNodes.size !== graph.nodes.length) throw Error('Повторяющийся gid');
    snapshot = {...graph, report}; nodes = nextNodes;
    top = [...graph.nodes].sort((a,b) => b.priority_score-a.priority_score || a.gid.localeCompare(b.gid)).slice(0,30);
    clusters = JSON.parse(fs.readFileSync(path.join(directory, 'clusters.json')));
    signals = JSON.parse(fs.readFileSync(path.join(directory,'signals.json')));
    rules = JSON.parse(fs.readFileSync(path.join(directory,'role_rules_resolved.json')));
  }
  reload();
  app.disable('x-powered-by');
  function authorize(req,res,next) {
    if (!allowRun) return res.status(403).json({error:'READ_ONLY'});
    if (req.get('X-Run-Token') !== token) return res.status(403).json({error:'SESSION_REQUIRED'});
    if (req.get('origin') && req.get('origin') !== `${req.protocol}://${req.get('host')}`) return res.status(403).json({error:'ORIGIN_REJECTED'});
    next();
  }
  app.post('/api/upload', authorize, express.json({limit:'36mb'}), (req,res) => {
    const files=req.body?.files, expected=['nodes.parquet','edges.parquet','transactions.parquet'];
    if (!Array.isArray(files)||files.length!==3||new Set(files.map(f=>f?.name)).size!==3||files.some(f=>!expected.includes(f?.name)))
      return res.status(400).json({error:'FILE_NAMES'});
    if (files.some(f=>typeof f.data!=='string'||f.data.length>Math.ceil(8*1024*1024/3)*4||!/^[A-Za-z0-9+/]*={0,2}$/.test(f.data)))
      return res.status(400).json({error:'FILE_SIZE_OR_ENCODING'});
    if (uploadBusy || job.status==='running') return res.status(409).json({error:'BUSY'});
    uploadBusy=true; let child;
    try {child=spawnProcess(python,['-B','-X','utf8','-m','python.memory_pipeline'],
                           {cwd:root,windowsHide:true,shell:false,env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}});}
    catch(error){uploadBusy=false;return res.status(500).json({error:'WORKER_START',detail:error.message});}
    let output='',bytes=0,finished=false;
    const finish=(code,data)=>{if(finished)return;finished=true;clearTimeout(timer);uploadBusy=false;if(!res.destroyed)res.status(code).json(data);};
    const timer=setTimeout(()=>{child.kill('SIGKILL');finish(408,{error:'TIMEOUT'});},timeout);
    child.stdout.setEncoding('utf8');
    child.stdout.on('data',chunk=>{bytes+=Buffer.byteLength(chunk);if(bytes>64*1024*1024){child.kill('SIGKILL');finish(413,{error:'RESULT_TOO_LARGE'});}else output+=chunk;});
    child.stderr.on('data',()=>{});
    child.stdin.on('error',()=>{});
    child.on('error',error=>finish(500,{error:'WORKER_START',detail:error.message}));
    child.on('close',code=>{if(finished)return;try{const data=JSON.parse(output);finish(code===0?200:422,code===0?data:{error:'INVALID_PARQUET',detail:data.error});}catch{finish(500,{error:'WORKER_RESPONSE'});}});
    res.on('close',()=>{if(!finished){child.kill('SIGKILL');finish(499,{error:'DISCONNECTED'});}});
    child.stdin.end(JSON.stringify({files}));
  });
  app.use(express.json({limit: '2kb'}));
  app.use((req,res,next) => {res.set('X-Content-Type-Options','nosniff'); next();});
  app.get('/api/graph', (req,res) => res.json(snapshot));
  app.get('/api/top', (req,res) => res.json(top));
  app.get('/api/clusters', (req,res) => res.json(clusters));
  app.get('/api/signals', (req,res) => res.json(signals));
  app.get('/api/dataset', (req,res) => res.json({graph:snapshot,clusters,signals,rules}));
  app.get('/api/nodes/:gid', (req,res) => {
    const node = nodes.get(req.params.gid);
    if (!node) return res.status(404).json({error:'gid не найден'});
    res.json({...node, edges:snapshot.edges.filter(e => e.from_gid === node.gid || e.to_gid === node.gid)});
  });
  app.get('/api/session', (req,res) => res.json({canRun:allowRun, token:allowRun ? token : null}));
  app.get('/api/pipeline/status', (req,res) => res.json(job));
  app.post('/api/pipeline', (req,res) => {
    if (!allowRun) return res.status(403).json({error:'Пересчёт отключён в режиме публикации'});
    if (req.get('X-Run-Token') !== token) return res.status(403).json({error:'Требуется токен локального сеанса'});
    if (req.get('origin') && req.get('origin') !== `${req.protocol}://${req.get('host')}`)
      return res.status(403).json({error:'Другой origin'});
    if (job.status === 'running' || uploadBusy) return res.status(409).json({error:'Уже выполняется'});
    job = {status:'running', startedAt:new Date().toISOString(), log:''};
    const staging = fs.mkdtempSync(path.join(path.dirname(output), 'run-'));
    let child;
    try {child = spawnProcess(python, ['-X','utf8',path.join(root,'python/run_pipeline.py'), '--out', staging],
                             {cwd:root, shell:false, windowsHide:true});}
    catch (error) {job = {...job,status:'failed',error:error.message}; return res.status(500).json(job);}
    let timedOut = false, completed = false;
    const timer = setTimeout(() => {timedOut=true; child.kill('SIGKILL');}, timeout);
    const append = chunk => {job.log = (job.log + chunk.toString()).slice(-16000);};
    child.stdout?.on('data',append); child.stderr?.on('data',append);
    child.on('error', error => {clearTimeout(timer); completed=true; job={...job,status:'failed',error:error.message};});
    child.on('close', code => {
      clearTimeout(timer); if (completed) return;
      if (code !== 0 || timedOut) {job={...job,status:'failed',error:timedOut?'Превышены 300 секунд':`Python exit ${code}`}; return;}
      // Serve the previous in-memory snapshot until all new artifacts have passed checks.
      try {
        const backup = `${output}.previous-${Date.now()}`;
        fs.renameSync(output,backup);
        try {fs.renameSync(staging,output); reload();}
        catch (error) {
          if (fs.existsSync(output)) fs.renameSync(output,staging);
          fs.renameSync(backup,output); reload(); throw error;
        }
        job={...job,status:'succeeded',finishedAt:new Date().toISOString(),report:snapshot.report};
      } catch (error) {job={...job,status:'failed',error:error.message};}
    });
    res.status(202).json({status:'running'});
  });
  const downloads = new Set(['nodes_roles.csv','clusters.csv','top_nodes.csv']);
  app.get('/api/download/:file', (req,res) => {
    if (!downloads.has(req.params.file)) return res.sendStatus(404);
    if (job.status === 'running') return res.status(409).send('Дождитесь завершения пересчёта');
    res.download(path.join(output,req.params.file));
  });
  app.use(express.static(path.join(root,'public')));
  app.use((error,req,res,next) => res.status(error.status||500).json({error:error.type==='entity.too.large'?'FILE_SIZE_OR_ENCODING':'REQUEST_FAILED'}));
  return app;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const host = process.env.HOST || '127.0.0.1', port = Number(process.env.PORT || 3000);
  const local = ['127.0.0.1','localhost','::1'].includes(host);
  const app = createApp({allowRun:local});
  const tls = process.env.HTTPS_KEY && process.env.HTTPS_CERT;
  const server = tls ? https.createServer({key:fs.readFileSync(process.env.HTTPS_KEY),cert:fs.readFileSync(process.env.HTTPS_CERT)},app) : http.createServer(app);
  server.listen(port,host,() => console.log(`Money Graph: ${tls?'https':'http'}://${host}:${port}`));
}
