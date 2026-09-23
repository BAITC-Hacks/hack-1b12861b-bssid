import Sigma from 'sigma';
import Graph from 'graphology';
import {EdgeArrowProgram} from 'sigma/rendering';
import {messages} from './i18n.js';
import {flowMessages,renderFlowDetails} from './flow-details.js';

const $=id=>document.getElementById(id), sections=['flow','clients','clusters','method'];
const roleKeys=['coordinator','consolidator','distributor','transit','terminal','peripheral'];
const colors={coordinator:'#ce8940',consolidator:'#319a81',distributor:'#648cd4',transit:'#9673cd',terminal:'#cf7b92',peripheral:'#708897'};
const storage={get:k=>{try{return localStorage.getItem(k);}catch{return null;}},set:(k,v)=>{try{localStorage.setItem(k,v);}catch{}}};
const state={lang:messages[storage.get('language')]?storage.get('language'):'ru',theme:storage.get('theme')==='light'?'light':'dark',section:sections.includes(location.hash.slice(1))?location.hash.slice(1):'flow',query:'',role:'',sort:'descending',page:0,pageSize:50,clusterQuery:'',clusterPage:0,onlySignals:false,clusterSort:'size',flowRole:'',flowCluster:'',color:'role',selected:null};
let dataset,original,session,renderer,graph,busy=false,nodeMap=new Map(),signalsByCluster=new Map();
const t=key=>messages[state.lang][key]||key, roleLabel=key=>messages[state.lang].roles[key]||key;
const locale=()=>({ru:'ru-RU',kk:'kk-KZ',en:'en-GB'}[state.lang]);
const number=(x,digits=0)=>x===null||x===undefined?t('unavailable'):new Intl.NumberFormat(locale(),{maximumFractionDigits:digits}).format(x);
const fixed=(x,digits=2)=>x===null||x===undefined?'—':new Intl.NumberFormat(locale(),{minimumFractionDigits:digits,maximumFractionDigits:digits}).format(x);
const percent=x=>x===null?'—':`${number(x*100,1)}%`;
const probability=x=>x<0.001?'< 0.001':fixed(x,3);
const h=(tag,text='',className='')=>{const el=document.createElement(tag);el.textContent=text;if(className)el.className=className;return el;};
function button(text,action,cls=''){const el=h('button',text,cls);el.type='button';el.onclick=action;return el;}
function field(label,element){const wrap=h('label','','field');wrap.append(h('span',label),element);return wrap;}
function select(id,options,value,handler){const el=h('select');el.id=id;for(const [val,text] of options)el.add(new Option(text,val));el.value=value;el.onchange=()=>handler(el.value);return el;}
function input(id,placeholder,value,handler){const el=h('input');el.id=id;el.placeholder=placeholder;el.value=value;el.autocomplete='off';el.oninput=()=>handler(el.value);return el;}
function details(title,text){const el=h('details');el.append(h('summary',title),h('p',text));return el;}
function badge(role){const b=h('span',roleLabel(role),'role-badge');b.style.setProperty('--role',colors[role]);return b;}
function notify(message='',error=false){$('notice').textContent=message;$('notice').className=error?'notice error':'notice';$('notice').hidden=!message;}
async function api(url,options){const res=await fetch(url,options);let data;try{data=await res.json();}catch{throw Error(t('error'));}if(!res.ok){const keys={FILE_NAMES:'invalidFiles',FILE_SIZE_OR_ENCODING:'fileLimit',INVALID_PARQUET:'schemaError',BUSY:'busy',TIMEOUT:'timeout',READ_ONLY:'readOnly'};const error=Error(t(keys[data.error]||'error'));error.detail=data.detail;throw error;}return data;}
function activate(data){dataset=data;nodeMap=new Map(dataset.graph.nodes.map(n=>[n.gid,n]));signalsByCluster=new Map();for(const row of dataset.signals.tests){if(!signalsByCluster.has(row.cluster_id))signalsByCluster.set(row.cluster_id,[]);signalsByCluster.get(row.cluster_id).push(row);}state.page=state.clusterPage=0;state.selected=null;state.flowCluster='';state.query=state.role=state.clusterQuery='';render();}
function priorityText(n){const w=dataset.rules.priority_weights;return `P = ${fixed(w.turnover)}×${fixed(n.priority_turnover,3)} + ${fixed(w.degree)}×${fixed(n.priority_degree,3)} + ${fixed(w.role)}×${fixed(n.priority_role,3)}`;}
function factText(n){return `${t('incoming')} ${number(n.in_deg)} / ${number(n.in_kzt)} KZT; ${t('outgoing')} ${number(n.out_deg)} / ${number(n.out_kzt)} KZT; k=${n.pass_through===null?'—':fixed(n.pass_through)}; ${t('depth')}=${n.depth}.`;}
function ruleText(n){return messages[state.lang].rules[n.rule_id]||t('unavailable');}
function monetaryThresholds(){const r=dataset.rules;return `Q${number(r.coordinator_turnover_quantile*100)}: ${number(r.coordinator_min_turnover,2)} KZT · Q${number(r.terminal_incoming_quantile*100)}: ${number(r.terminal_min_incoming,2)} KZT`;}
function applyTheme(){document.documentElement.dataset.theme=state.theme;storage.set('theme',state.theme);const tg=window.Telegram?.WebApp;if(tg?.initData){tg.setHeaderColor(state.theme==='dark'?'#111b23':'#f7f9fa');tg.setBackgroundColor(state.theme==='dark'?'#0d151c':'#eff3f5');}}
function updateBusy(){for(const id of ['upload','run','restore'])$(id).disabled=busy||(!session?.canRun&&id!=='restore');}
function render(){
 if(!dataset)return;
 renderer?.kill();renderer=null;applyTheme();document.documentElement.lang=state.lang;document.title=t('brand');
 $('brand').replaceChildren(h('strong',t('brand')),h('small',t('brandSub')));$('nav-label').textContent=t('nav');
 $('navigation').replaceChildren();sections.forEach((key,i)=>{const b=button('',()=>{location.hash=key;},state.section===key?'nav-item active':'nav-item');b.dataset.section=key;b.setAttribute('aria-current',state.section===key?'page':'false');b.append(h('span',['↗','≡','◈','ⓘ'][i],'nav-icon'),h('span',t(key)));$('navigation').append(b);});
 const uploaded=!!dataset.csvs;$('source').textContent=t(uploaded?'uploaded':'builtin');$('upload').textContent=t('upload');$('upload-hint').textContent=t('uploadHint');$('upload').title=t('memoryHint');$('restore').textContent=t('restore');$('restore').hidden=!uploaded;
 $('language').value=state.lang;$('theme').textContent=t(state.theme==='dark'?'light':'dark');$('mode').textContent=t('local');$('run').textContent=t('run');$('run').hidden=uploaded||!session?.canRun;
 $('breadcrumb').textContent=`${t('brand')} / ${t(state.section)}`;$('eyebrow').textContent=`0${sections.indexOf(state.section)+1} / ${t('nav')}`;$('title').textContent=t(state.section);$('subtitle').textContent=messages[state.lang].subtitles[state.section];
 const fm=flowMessages[state.lang];$('stats').replaceChildren();for(const [label,value,note] of [[t('count'),number(dataset.graph.nodes.length)],[t('seeds'),number(dataset.graph.nodes.filter(n=>n.is_seed).length)],[t('turnover'),number(dataset.graph.report.metrics.sum_in_kzt)],[fm.communities,`${number(dataset.clusters.length)} / ${number(dataset.clusters.filter(c=>c.n_seed>1).length)}`],[fm.boundary,number(dataset.graph.nodes.filter(n=>n.truncated_by_depth).length),fm.boundaryHint]]){const card=h('div');card.append(h('small',label),h('strong',value));if(note)card.append(h('p',note,'stat-note'));$('stats').append(card);}
 $('footnote').textContent=t('footnote');$('downloads').replaceChildren();for(const [file,key] of [['nodes_roles.csv','csvRoles'],['clusters.csv','csvClusters'],['top_nodes.csv','csvTop']])$('downloads').append(button(`${t(key)} ↓`,()=>download(file),'download'));
 $('content').replaceChildren();({flow:renderFlow,clients:renderClients,clusters:renderClusters,method:renderMethod})[state.section]();updateBusy();
}
function paginate(container,total,page,size,change){
 const bar=h('div','','pagination'),pages=Math.max(1,Math.ceil(total/size));const prev=button(t('prev'),()=>change(page-1));prev.disabled=page===0;const next=button(t('next'),()=>change(page+1));next.disabled=page>=pages-1;
 bar.append(h('span',`${number(total? page*size+1:0)}–${number(Math.min(total,(page+1)*size))} ${t('of')} ${number(total)}`),prev,h('span',`${page+1} / ${pages}`),next);container.append(bar);
}
function table(headers){const wrap=h('div','','table-wrap'),tab=h('table'),head=h('thead'),tr=h('tr'),body=h('tbody');for(const label of headers){const th=h('th',label);th.scope='col';tr.append(th);}head.append(tr);tab.append(head,body);wrap.append(tab);return {wrap,body};}
function renderClients(){
 const controls=h('div','','controls');const roleOptions=[['',t('allRoles')],...roleKeys.map(k=>[k,roleLabel(k)])];
 controls.append(field(t('search'),input('client-search',t('searchHint'),state.query,v=>{state.query=v.trim();state.page=0;renderClientRows();})),field(t('role'),select('client-role',roleOptions,state.role,v=>{state.role=v;state.page=0;renderClientRows();})),field(t('sort'),select('client-sort',['descending','ascending','gidSort'].map(k=>[k,t(k)]),state.sort,v=>{state.sort=v;state.page=0;renderClientRows();})),field(t('rows'),select('page-size',[['50','50'],['100','100'],['500','500'],['100000',t('all')]],String(state.pageSize),v=>{state.pageSize=Number(v);state.page=0;renderClientRows();})));
 const panel=h('div','','panel');panel.id='client-list';$('content').append(controls,panel);renderClientRows();
}
function renderClientRows(){
 const rows=dataset.graph.nodes.filter(n=>n.gid.includes(state.query)&&(!state.role||n.role===state.role));
 const idCompare=(a,b)=>a.gid.length-b.gid.length||a.gid.localeCompare(b.gid);
 rows.sort(state.sort==='gidSort'?idCompare:(a,b)=>(state.sort==='ascending'?1:-1)*(a.priority_score-b.priority_score)||idCompare(a,b));
 state.page=Math.min(state.page,Math.max(0,Math.ceil(rows.length/state.pageSize)-1));const panel=$('client-list');panel.replaceChildren();
 const {wrap,body}=table(['GID',t('role'),t('priority'),t('explanation')]);wrap.classList.add('client-table');
 for(const n of rows.slice(state.page*state.pageSize,(state.page+1)*state.pageSize)){
  const tr=h('tr');tr.dataset.gid=n.gid;const gid=h('td',n.gid,'mono');const role=h('td');role.append(badge(n.role));const score=h('td','','score');const track=h('div','','track');const fill=h('i');fill.style.width=`${100*n.priority_score}%`;track.append(fill);score.append(h('strong',fixed(n.priority_score,3)),track);
  const facts=h('td','','facts');facts.append(h('strong',ruleText(n)),h('p',factText(n)),h('small',priorityText(n)));tr.append(gid,role,score,facts);body.append(tr);
 }
 panel.append(wrap);if(!rows.length)panel.append(h('p',t('empty'),'empty'));paginate(panel,rows.length,state.page,state.pageSize,page=>{state.page=page;renderClientRows();panel.scrollIntoView({block:'start'});});
}
function renderClusters(){
 const controls=h('div','','controls');controls.append(field(t('clusterFilter'),input('cluster-query','ID',state.clusterQuery,v=>{state.clusterQuery=v.trim();state.clusterPage=0;renderClusterRows();})),field(t('sort'),select('cluster-sort',[['size',t('bySize')],['q',t('bySignal')]],state.clusterSort,v=>{state.clusterSort=v;state.clusterPage=0;renderClusterRows();})));
 const label=h('label','','check'),box=h('input');box.type='checkbox';box.id='signals-only';box.checked=state.onlySignals;box.onchange=()=>{state.onlySignals=box.checked;state.clusterPage=0;renderClusterRows();};label.append(box,h('span',t('signalsOnly')));controls.append(label);
 const info=h('div','','callout');info.append(h('strong',t('statNote')),h('p',`${t('tests')}: ${dataset.signals.n_tests} · ${t('threshold')}`));
 const list=h('div');list.id='cluster-list';$('content').append(info,controls,list);renderClusterRows();
}
function renderClusterRows(){
 const minQ=c=>Math.min(...signalsByCluster.get(c.cluster_id).map(r=>r.q_value));
 const rows=dataset.clusters.filter(c=>String(c.cluster_id).includes(state.clusterQuery)&&(!state.onlySignals||minQ(c)<.05));rows.sort(state.clusterSort==='q'?(a,b)=>minQ(a)-minQ(b)||a.cluster_id-b.cluster_id:(a,b)=>b.n_nodes-a.n_nodes||a.cluster_id-b.cluster_id);
 const panel=$('cluster-list');panel.replaceChildren();state.clusterPage=Math.min(state.clusterPage,Math.max(0,Math.ceil(rows.length/8)-1));
 for(const c of rows.slice(state.clusterPage*8,(state.clusterPage+1)*8)){
  const signals=signalsByCluster.get(c.cluster_id),card=h('article','','panel cluster-card');const head=h('div','','cluster-head');head.append(h('h2',`${t('cluster')} ${c.cluster_id}`));
  for(const [label,value] of [[t('size'),number(c.n_nodes)],[t('seedCount'),number(c.n_seed)],[t('internal'),`${number(c.sum_kzt_internal)} KZT`]]){const el=h('div');el.append(h('small',label),h('strong',value));head.append(el);}card.append(head);
  const detected=signals.filter(s=>s.q_value<.05);card.append(h('p',detected.length?t('clusterSignal')+detected.map(s=>`${roleLabel(s.role)} ${s.odds_ratio>1?'↑':'↓'}`).join(' · '):t('noSignal'),'cluster-summary'));
  const {wrap,body}=table([t('role'),t('inside'),t('outside'),'OR',t('ci'),'q-value',t('signal')]);
  for(const s of signals){const tr=h('tr');const role=h('td');role.append(badge(s.role));tr.append(role);for(const [share,count,total] of [[s.inside_share,s.inside_role,c.n_nodes],[s.outside_share,s.outside_role,dataset.graph.nodes.length-c.n_nodes]]){const td=h('td');td.append(h('strong',percent(share)),h('small',`${count} / ${total}`));tr.append(td);}tr.append(h('td',s.odds_ratio===null?'—':`${fixed(s.odds_ratio)}${s.zero_correction?'*':''}`),h('td',s.ci_low===null?'—':`${fixed(s.ci_low)}–${fixed(s.ci_high)}`,'nowrap'),h('td',probability(s.q_value),'mono'));const sig=h('td');sig.append(h('span',t(s.signal),s.q_value<.05?'signal flagged':'signal'));tr.append(sig);body.append(tr);}
  card.append(wrap,h('p',t('orNote'),'small-note'));if(signals.some(s=>s.sparse))card.append(h('p',t('sparse'),'small-note'));panel.append(card);
 }
 if(!rows.length)panel.append(h('p',t('empty'),'empty'));paginate(panel,rows.length,state.clusterPage,8,page=>{state.clusterPage=page;renderClusterRows();$('content').scrollIntoView({block:'start'});});
}
function roleConditions(){const r=dataset.rules;return [
 `in_deg ≥ ${r.coordinator_in_degree}; out_deg ≥ ${r.coordinator_out_degree}; in_kzt + out_kzt ≥ ${number(r.coordinator_min_turnover,2)} KZT`,
 `${t('incoming')} ≥ ${r.consolidator_in_degree}; k ≤ ${r.consolidator_max_pass_through}; is_seed = false`,
 `${t('outgoing')} ≥ ${r.distributor_out_degree}`,
 `${r.transit_min_pass_through} ≤ k ≤ ${r.transit_max_pass_through}; ${t('incoming')}, ${t('outgoing')} > 0; is_seed = false`,
 `depth < 4; ${t('outgoing')} = 0; ${t('incoming')} ≥ ${number(r.terminal_min_incoming,2)} KZT; is_seed = false`,
 messages[state.lang].rules.no_rule];}
function renderMethod(){
 const hero=h('div','','panel method-hero'),w=dataset.rules.priority_weights;hero.append(h('div',t('methodTitle'),'eyebrow'),h('h2',`P = ${fixed(w.turnover)} × T + ${fixed(w.degree)} × D + ${fixed(w.role)} × R`,'formula'),h('p',t('formulaText')));
 const rules=h('div','','panel method-rules');rules.append(h('h2',t('ruleTitle')),h('p',t('ruleIntro')),h('p',`${t('thresholds')}: ${monetaryThresholds()}`,'small-note'));const {wrap,body}=table(['#',t('role'),t('ruleDetails'),t('support')]);const conditions=roleConditions(),order=['coordinator','distributor','consolidator','transit','terminal','peripheral'];for(const [i,role] of order.entries()){const row=h('tr'),label=h('td');label.append(badge(role));row.append(h('td',String(i+1)),label,h('td',conditions[roleKeys.indexOf(role)]),h('td',{coordinator:'0.65',distributor:'0.75',consolidator:'0.70',transit:'0.60',terminal:'0.50',peripheral:'0.25 / 0.10'}[role]));body.append(row);}rules.append(wrap);
 $('content').append(hero,rules);for(const [title,text] of [['detailsPriority','priorityLong'],['detailsStats','statsLong'],['detailsLimits','limitsLong'],['detailsUpload','uploadLong']])$('content').append(details(t(title),t(text)));
}
function renderFlow(){
 const toolbar=h('div','','controls');const search=input('flow-search','GID',state.selected||'',()=>{});const find=()=>selectNode(search.value.trim());search.onkeydown=e=>{if(e.key==='Enter')find();};toolbar.append(field(t('search'),search),button(t('find'),find),field(t('color'),select('flow-color',[['role',t('byRole')],['cluster',t('byCluster')]],state.color,v=>{state.color=v;renderer.refresh();})),field(t('role'),select('flow-role',[['',t('allRoles')],...roleKeys.map(k=>[k,roleLabel(k)])],state.flowRole,v=>{state.flowRole=v;state.selected=null;renderer.refresh();renderNodeCard();})),field(t('cluster'),select('flow-cluster',[['',t('all')],...dataset.clusters.map(c=>[String(c.cluster_id),`#${c.cluster_id} · ${c.n_nodes}`])],state.flowCluster,v=>{state.flowCluster=v;state.selected=null;renderer.refresh();renderNodeCard();})));
 const layout=h('div','','flow-layout'),panel=h('div','','graph-panel'),canvas=h('div');canvas.id='graph';const controls=h('div','','graph-tools');controls.append(button(t('reset'),()=>{state.selected=null;state.flowRole=state.flowCluster='';$('flow-role').value=$('flow-cluster').value='';renderer.refresh();renderer.getCamera().animatedReset();renderNodeCard();}),button('+',()=>renderer.getCamera().animatedZoom()),button('−',()=>renderer.getCamera().animatedUnzoom()));panel.append(canvas,h('div',t('graphNote'),'graph-note'),controls);const detail=h('aside','','panel node-panel');detail.id='flow-card';const graphColumn=h('div','','flow-graph-column'),mini=h('div','','panel mini-map');mini.id='flow-mini';mini.hidden=true;graphColumn.append(panel,mini);layout.append(graphColumn,detail);$('content').append(toolbar,layout);buildGraph();renderNodeCard();
}
function buildGraph(){
 graph=new Graph({type:'directed',allowSelfLoops:true});const members=new Map();for(const node of dataset.graph.nodes){if(!members.has(node.cluster_id))members.set(node.cluster_id,[]);members.get(node.cluster_id).push(node);}let index=0;for(const nodes of members.values()){const i=index++,angle=i*2.3999632297,radius=7*Math.sqrt(i),cx=radius*Math.cos(angle),cy=radius*Math.sin(angle);nodes.forEach((n,j)=>graph.addNode(n.gid,{...n,x:cx+.3*Math.sqrt(j)*Math.cos(j*2.399963),y:cy+.3*Math.sqrt(j)*Math.sin(j*2.399963),size:2+6*n.priority_score,label:n.gid,color:colors[n.role]}));}
 dataset.graph.edges.forEach((e,i)=>graph.addEdgeWithKey(String(i),e.from_gid,e.to_gid,{size:.5,color:state.theme==='dark'?'#314954':'#c0cdd3',type:'arrow'}));
 const match=n=>(!state.flowRole||n.role===state.flowRole)&&(!state.flowCluster||String(n.cluster_id)===state.flowCluster);
 renderer=new Sigma(graph,$('graph'),{allowInvalidContainer:false,defaultEdgeType:'arrow',edgeProgramClasses:{arrow:EdgeArrowProgram},labelColor:{color:state.theme==='dark'?'#d8e6ec':'#1a3741'},labelSize:11,labelRenderedSizeThreshold:9,
 defaultDrawNodeHover:(ctx,n)=>{ctx.font='11px Segoe UI';const label=n.label||'',w=ctx.measureText(label).width;ctx.fillStyle=state.theme==='dark'?'#22413b':'#daeae6';ctx.fillRect(n.x+n.size+2,n.y-10,w+10,21);ctx.fillStyle=state.theme==='dark'?'#effffb':'#152c29';ctx.fillText(label,n.x+n.size+6,n.y+4);ctx.beginPath();ctx.arc(n.x,n.y,n.size,0,Math.PI*2);ctx.fillStyle=n.color;ctx.fill();},
 nodeReducer:(gid,attrs)=>{const n={...attrs};if(!match(n))return {...n,hidden:true};n.color=state.color==='cluster'?`hsl(${n.cluster_id*137.508%360},50%,55%)`:colors[n.role];if(state.selected&&gid!==state.selected&&!graph.hasEdge(gid,state.selected)&&!graph.hasEdge(state.selected,gid)){n.color=state.theme==='dark'?'#263842':'#d8e0e4';n.label='';n.size=1.5;}if(gid===state.selected){n.size=11;n.highlighted=n.forceLabel=true;}return n;},
 edgeReducer:(key,attrs)=>{const s=graph.source(key),d=graph.target(key);if(!match(graph.getNodeAttributes(s))||!match(graph.getNodeAttributes(d)))return {...attrs,hidden:true};return state.selected?{...attrs,hidden:s!==state.selected&&d!==state.selected,color:s===state.selected?'#ce8940':'#319a81',size:1.5}:attrs;}});
 renderer.on('clickNode',({node})=>selectNode(node));
}
function selectNode(gid){if(!nodeMap.has(gid))return notify(t('notFound'),true);notify();state.selected=gid;state.flowRole=state.flowCluster='';$('flow-role').value=$('flow-cluster').value='';$('flow-search').value=gid;renderer.refresh();const p=renderer.getNodeDisplayData(gid);renderer.getCamera().animate({x:p.x,y:p.y,ratio:.24},{duration:350});renderNodeCard();}
function renderNodeCard(){
 const card=$('flow-card');card.replaceChildren(h('h2',t('card')));const n=nodeMap.get(state.selected);
 if(n){renderFlowDetails({card,mini:$('flow-mini'),n,dataset,lang:state.lang,h,button,details,badge,t,number,fixed,percent,ruleText,condition:n.role==='peripheral'?'':roleConditions()[roleKeys.indexOf(n.role)],selectNode});}
 else{$('flow-mini').hidden=true;card.append(h('p',t('selectNode'),'empty'),h('h3',t('top')));for(const n of [...dataset.graph.nodes].sort((a,b)=>b.priority_score-a.priority_score||a.gid.localeCompare(b.gid)).slice(0,30)){const b=button(n.gid,()=>selectNode(n.gid),'neighbor');b.append(h('small',`${roleLabel(n.role)} · ${fixed(n.priority_score,3)}`));card.append(b);}}
}
async function download(file){try{let blob;if(dataset.csvs)blob=new Blob(['\ufeff',dataset.csvs[file]],{type:'text/csv;charset=utf-8'});else{const res=await fetch(`/api/download/${file}`);if(!res.ok)throw Error(t('error'));blob=await res.blob();}const url=URL.createObjectURL(blob),a=h('a');a.href=url;a.download=file;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){notify(e.message,true);}}
async function upload(files){
 const names=['nodes.parquet','edges.parquet','transactions.parquet'];if(files.length!==3||new Set(files.map(f=>f.name)).size!==3||files.some(f=>!names.includes(f.name)))return notify(t('invalidFiles'),true);
 if(files.some(f=>f.size===0||f.size>8*1024*1024))return notify(t('fileLimit'),true);
 busy=true;updateBusy();notify(t('loading'));
 try{const encoded=await Promise.all(files.map(file=>new Promise((resolve,reject)=>{const reader=new FileReader();reader.onerror=()=>reject(Error(t('error')));reader.onload=()=>resolve({name:file.name,data:reader.result.split(',')[1]});reader.readAsDataURL(file);})));const result=await api('/api/upload',{method:'POST',headers:{'Content-Type':'application/json','X-Run-Token':session.token},body:JSON.stringify({files:encoded})});activate(result);notify(t('loaded'));}
 catch(e){notify(e.message,true);if(e.detail)$('notice').append(details('Parquet',e.detail));}
 finally{busy=false;updateBusy();$('files').value='';}
}
$('language').onchange=()=>{state.lang=$('language').value;storage.set('language',state.lang);notify();render();};$('theme').onclick=()=>{state.theme=state.theme==='dark'?'light':'dark';render();};
$('upload').onclick=()=>{if(session?.canRun)$('files').click();else notify(t('readOnly'),true);};$('files').onchange=()=>upload([...$('files').files]);$('restore').onclick=()=>{activate(original);notify();};
$('run').onclick=async()=>{busy=true;updateBusy();notify(t('loading'));try{await api('/api/pipeline',{method:'POST',headers:{'X-Run-Token':session.token}});let done=false;while(!done){await new Promise(r=>setTimeout(r,600));const job=await api('/api/pipeline/status');if(job.status==='failed')throw Error(t('error'));if(job.status==='succeeded'){original=await api('/api/dataset');activate(original);notify(`${number(original.graph.report.elapsed_seconds,2)} ${t('seconds')}`);done=true;}}}catch(e){notify(e.message,true);}finally{busy=false;updateBusy();}};
window.onhashchange=()=>{state.section=sections.includes(location.hash.slice(1))?location.hash.slice(1):'flow';notify();render();window.scrollTo({top:0});};
(async()=>{try{applyTheme();session=await api('/api/session');original=await api('/api/dataset');activate(original);const tg=window.Telegram?.WebApp;if(tg?.initData){tg.ready();tg.expand();}}catch(e){notify(`${t('error')}: ${e.message}`,true);}})();

