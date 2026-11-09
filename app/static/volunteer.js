'use strict';
const root=document.querySelector('#station'),cid=root.dataset.challenge,manual=root.dataset.mode==='manual';
const $=id=>document.getElementById(id),csrf=document.querySelector('meta[name="csrf-token"]').content;
let player=null, snapshot=null, busy=false, syncAt=0, elapsed=0, pending=null, refreshSequence=0;
const pendingKey=`glua-pending-${cid}`;
try{pending=JSON.parse(sessionStorage.getItem(pendingKey)||'null');}catch(_){}
function rememberPending(){try{if(pending)sessionStorage.setItem(pendingKey,JSON.stringify(pending));else sessionStorage.removeItem(pendingKey);}catch(_){}}
const clock=n=>`${String(Math.floor(n/6000)).padStart(2,'0')}:${String(Math.floor(n/100)%60).padStart(2,'0')}.${String(n%100).padStart(2,'0')}`;
function message(s){$('message').textContent=s;}
async function api(path,payload){
 const response=await fetch(path,payload?{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(payload)}:{});
 if(!response.headers.get('Content-Type')?.includes('application/json'))throw Error('Sessão expirada ou servidor indisponível. Atualiza a página e entra novamente.');
 const result=await response.json();if(!response.ok)throw Error(result.error||'Pedido recusado. Atualiza a página e verifica a sessão.');return result;
}
function controls(){
 const a=snapshot?.active,own=a&&a.participant_id===player?.id,ready=player&&snapshot?.remaining>0&&!a&&!busy;
 if(!manual){$('start').disabled=!ready;$('stop').disabled=busy||!own||a.status!=='running';}
 $('save').disabled=busy||(manual?!ready:!own||a.status!=='stopped');
 $('failed').disabled=busy||!(ready||own);
 $('players').disabled=busy||!!a;$('register').disabled=busy||!!a;
}
async function refresh(){
 const selected=player?.id, sequence=++refreshSequence;
 const state=await api(`/api/state/${cid}${selected?'?player='+selected:''}`);
 if(selected!==player?.id||sequence!==refreshSequence)return;
 snapshot=state;syncAt=performance.now();elapsed=state.active?.elapsed||state.active?.centiseconds||0;
 if(state.active&&!player){player={id:state.active.participant_id,nickname:state.active.nickname};await refresh();return;}
 $('selected').textContent=player?`Jogador: ${player.nickname} (#${player.id})`:'Nenhum jogador selecionado';
 $('remaining').textContent=player?`${state.remaining} tentativa(s) disponível(is) de 3`:'';
 $('active').textContent=state.active?`Tentativa #${state.active.number}: ${state.active.nickname} · ${state.active.status==='running'?'a decorrer':'parada — confirmar resultado'}`:'';
 $('history').replaceChildren();for(const a of state.attempts){const li=document.createElement('li');li.textContent=`${a.number}/3 · ${a.status} · ${clock(a.centiseconds||0)}${a.note?' · '+a.note:''}`;$('history').append(li);}
 controls();
}
let searchSequence=0;
async function search(){const sequence=++searchSequence;try{const rows=await api('/api/players?q='+encodeURIComponent($('search').value));if(sequence!==searchSequence)return;$('players').replaceChildren();for(const r of rows){const option=new Option(`${r.nickname} (#${r.id})`,r.id);option.dataset.nickname=r.nickname;$('players').add(option);}}catch(e){message(e.message);}}
$('search').addEventListener('input',search);
$('players').addEventListener('change',async()=>{const o=$('players').selectedOptions[0];if(!o)return;player={id:Number(o.value),nickname:o.dataset.nickname};try{await refresh();}catch(e){message(e.message);}});
$('register').onclick=async()=>{if(busy)return;busy=true;controls();try{player=await api('/api/players',{nickname:$('search').value});message('Jogador registado.');await search();await refresh();}catch(e){message(e.message);}finally{busy=false;controls();}};
async function act(action){
 if(busy||!player)return;
 if(action==='failed'&&!confirm(`Contar uma tentativa falhada para ${player.nickname}?`))return;
 busy=true;controls();
 try{
  const a=snapshot?.active;
  if(['stop','save','failed'].includes(action)&&a){
   if(a.participant_id!==player.id)throw Error('A estação está ocupada por outro jogador.');
   await api(`/api/attempts/${a.id}/${action}`,{});
  }else{
   const payload={player:player.id,action:manual&&action==='save'?'manual':action,time:manual?$('race-time').value:null};
   const signature=JSON.stringify(payload);
   // Keep the same request token after a lost network response.
   if(!pending||pending.signature!==signature)pending={signature,token:cryptoToken()};
   rememberPending();
   await api(`/api/attempt/${cid}`,{...payload,token:pending.token});pending=null;rememberPending();
   if(manual)$('race-time').value='';
  }
  message(action==='stop'?'Tempo parado. Confirma e guarda.':'Operação registada.');await refresh();
 }catch(e){message(e.message);try{await refresh();}catch(_){} }
 finally{busy=false;controls();}
}
function cryptoToken(){const bytes=new Uint8Array(24);crypto.getRandomValues(bytes);return Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');}
for(const id of ['start','stop','save','failed'])if($(id))$(id).onclick=()=>act(id);
setInterval(()=>{if(!manual&&snapshot){const n=snapshot.active?.status==='running'?elapsed+Math.floor((performance.now()-syncAt)/10):elapsed;$('timer').textContent=clock(n);}},40);
setInterval(()=>{if(!busy)refresh().catch(e=>message('Sem ligação: '+e.message));},2000);
search();refresh().catch(e=>message(e.message));
