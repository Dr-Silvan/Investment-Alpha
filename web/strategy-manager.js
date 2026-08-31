export function install({state,viewOverrides,api,load,toast}){
  wrap('importPosition','swing');
  wrap('planner','swing');

  function wrap(view,mode){
    const base=viewOverrides[view];
    viewOverrides[view]=()=>{
      base();
      if(view==='planner')syncPlannerChoices();
      const head=document.querySelector('#content .card-head');
      if(!head)return;
      head.insertAdjacentHTML('beforeend','<button class="btn ghost strategy-manage" type="button">전략 관리</button>');
      head.querySelector('.strategy-manage').onclick=()=>openManager(mode,view);
    };
  }

  function syncPlannerChoices(){
    const form=document.querySelector('#tradeForm');if(!form)return;
    const active=state.data.strategies.filter(row=>row.mode==='swing'&&row.active);
    const selected=new Set([...form.querySelectorAll('input[name="evidence"]:checked')].map(input=>input.value));
    form.querySelectorAll('.evidence-group').forEach(group=>group.remove());
    const anchor=form.querySelector('.confluence-summary');
    const groups={};active.forEach(row=>(groups[row.group_name]??=[]).push(row.label));
    anchor.insertAdjacentHTML('beforebegin',Object.entries(groups).map(([group,items])=>`<div class="evidence-group"><h3>${group}</h3><div class="chip-grid">${items.map(item=>`<label class="evidence-chip"><input type="checkbox" name="evidence" data-group="${group}" value="${item}" ${selected.has(item)?'checked':''}><span>${item}</span></label>`).join('')}</div></div>`).join(''));
  }

  function usage(label){
    let count=0;
    [...(state.data.positions||[]),...(state.data.closedPositions||[]),...(state.data.active||[]),...(state.data.planned||[])].forEach(item=>{try{const evidence=JSON.parse(item.evidence_json||'{}');if(Object.values(evidence).flat().includes(label))count++}catch{}});
    (state.data.dayTrades||[]).forEach(item=>{try{if(JSON.parse(item.strategies_json||'[]').includes(label))count++}catch{}});
    return count;
  }

  function openManager(mode,returnView){
    const modal=document.createElement('div'),rows=state.data.strategies.filter(row=>row.mode===mode);
    modal.className='modal-backdrop';
    modal.innerHTML=`<div class="modal-panel"><div class="modal-head"><div><h2>전략 카탈로그 관리</h2><p class="sub">보관된 전략은 선택 목록에서만 숨겨지며 과거 거래와 통계에는 유지됩니다.</p></div><button class="btn ghost" data-dismiss>닫기</button></div><div class="modal-body"><form id="strategyAdd"><div class="row"><label>섹션<input name="group" list="strategyGroups" required></label><label>새 전략<input name="label" required placeholder="예: Drop Test 재확인"></label></div><datalist id="strategyGroups">${[...new Set(rows.map(row=>row.group_name))].map(group=>`<option value="${group}">`).join('')}</datalist><button class="btn" type="submit">전략 추가</button></form><div class="strategy-manager-list">${rows.map(row=>`<div class="mini-stat"><span><strong>${row.label}</strong><br><small>${row.group_name} · 사용 ${usage(row.label)}회 ${row.active?'':'· 보관됨'}</small></span><button class="btn ghost" data-strategy="${row.id}" data-active="${row.active?0:1}">${row.active?'표시에서 숨기기':'다시 표시'}</button></div>`).join('')}</div></div></div>`;
    document.body.appendChild(modal);
    modal.querySelector('[data-dismiss]').onclick=()=>modal.remove();
    modal.querySelectorAll('[data-strategy]').forEach(button=>button.onclick=async()=>{try{await api(`/api/strategies/${button.dataset.strategy}`,{method:'PATCH',body:JSON.stringify({active:button.dataset.active==='1'})});await load();modal.remove();toast('전략 표시 상태를 변경했습니다. 과거 통계는 유지됩니다.');viewOverrides[returnView]()}catch(error){toast(error.message)}});
    modal.querySelector('#strategyAdd').onsubmit=async event=>{event.preventDefault();const payload=Object.fromEntries(new FormData(event.currentTarget));payload.mode=mode;try{await api('/api/strategies',{method:'POST',body:JSON.stringify(payload)});await load();modal.remove();toast('새 전략을 추가했습니다.');viewOverrides[returnView]()}catch(error){toast(error.message)}};
  }
}
