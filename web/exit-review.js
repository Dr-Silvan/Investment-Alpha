const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const request=async(path,options={})=>{const response=await fetch(path,{headers:{'Content-Type':'application/json'},...options}),data=await response.json();if(!response.ok)throw new Error(data.error||'요청에 실패했습니다.');return data};

function open({ticker,defaultPrice,defaultDate,exitReview={},manageStrategies,strategies=[],evidence={},exitReasons=[]}){
  return new Promise(resolve=>{
    const root=document.createElement('div');root.className='modal-backdrop';
    let catalog=exitReasons;

    const readForm=()=>{
      const form=root.querySelector('form');
      if(!form)return {exitPrice:defaultPrice,closedAt:defaultDate||new Date().toISOString().slice(0,10),exitReview:{...exitReview},evidence:{...evidence}};
      const review={ruleBased:form.elements.ruleBased?.value==='true',note:form.elements.note?.value||''},updatedEvidence={};
      form.querySelectorAll('input[name="reason"]:checked').forEach(input=>(review[input.dataset.group]??=[]).push(input.value));
      form.querySelectorAll('input[name="strategy"]:checked').forEach(input=>(updatedEvidence[input.dataset.strategyGroup]??=[]).push(input.value));
      return {exitPrice:+form.elements.exitPrice.value,closedAt:form.elements.closedAt.value,exitReview:review,evidence:updatedEvidence};
    };

    const render=(values={exitPrice:defaultPrice,closedAt:defaultDate||new Date().toISOString().slice(0,10),exitReview,evidence})=>{
      const review=values.exitReview||{},selectedReasons=new Set(Object.entries(review).filter(([,items])=>Array.isArray(items)).flatMap(([,items])=>items));
      const visibleReasons=catalog.filter(row=>row.active||selectedReasons.has(row.label)),reasonGroups={};
      visibleReasons.forEach(row=>(reasonGroups[row.group_name]??=[]).push(row));
      const selectedStrategies=new Set(Object.values(values.evidence||{}).flat()),strategyCatalog=strategies.filter(row=>row.mode==='swing'&&(row.active||selectedStrategies.has(row.label))),strategyGroups={};
      strategyCatalog.forEach(row=>(strategyGroups[row.group_name]??=[]).push(row));
      root.innerHTML=`<div class="modal-panel"><div class="modal-head"><div><h2>${esc(ticker)} Exit Review</h2><p class="sub">매도 당시 알 수 있었던 근거만 기록하세요.</p></div><div style="display:flex;gap:8px;flex-wrap:wrap">${manageStrategies?'<button class="btn ghost" type="button" data-manage-strategies>진입 전략 관리</button>':''}<button class="btn ghost" type="button" data-manage-exit-reasons>청산 항목 관리</button><button class="btn ghost" type="button" data-close>닫기</button></div></div><form id="exitReviewForm"><div class="modal-body"><div class="row"><label>종료가 (USD)<input name="exitPrice" type="number" step="0.01" value="${values.exitPrice}" required></label><label>종료일<input name="closedAt" type="date" value="${esc(values.closedAt)}" required></label></div>${strategyCatalog.length?`<details class="reason-details"><summary>적용 전략</summary>${Object.entries(strategyGroups).map(([group,items])=>`<div style="padding:0 14px 12px"><strong>${esc(group)}</strong><div class="chip-grid">${items.map(item=>`<label class="evidence-chip"><input type="checkbox" name="strategy" data-strategy-group="${esc(group)}" value="${esc(item.label)}" ${selectedStrategies.has(item.label)?'checked':''}><span>${esc(item.label)}${item.active?'':' · 숨김'}</span></label>`).join('')}</div></div>`).join('')}</details>`:''}<div><p class="sub">이 매도는 사전에 정의한 규칙에 따른 것인가?</p><div class="rule-choice"><label><input type="radio" name="ruleBased" value="true" ${review.ruleBased===true?'checked':''} required> 예, 계획된 규칙</label><label><input type="radio" name="ruleBased" value="false" ${review.ruleBased===false?'checked':''} required> 아니오, 재량 판단</label></div></div>${Object.entries(reasonGroups).map(([group,items],index)=>`<details class="reason-details" ${index===0?'open':''}><summary>${esc(group)}</summary><div class="chip-grid">${items.map(item=>`<label class="evidence-chip"><input type="checkbox" name="reason" data-group="${esc(group)}" value="${esc(item.label)}" ${selectedReasons.has(item.label)?'checked':''}><span>${esc(item.label)}${item.active?'':' · 숨김'}</span></label>`).join('')}</div></details>`).join('')}<label>매도 메모<textarea name="note" placeholder="무엇이 바뀌어서 포지션을 종료했는가?">${esc(review.note)}</textarea></label></div><div class="modal-actions"><button type="button" class="btn ghost" data-close>취소</button><button type="submit" class="btn">종료 기록 저장</button></div></form></div>`;
      root.querySelectorAll('[data-close]').forEach(button=>button.onclick=()=>{root.remove();resolve(null)});
      root.querySelector('[data-manage-exit-reasons]').onclick=openManager;
      const manage=root.querySelector('[data-manage-strategies]');if(manage)manage.onclick=()=>manageStrategies();
      root.querySelector('form').onsubmit=event=>{event.preventDefault();const value=readForm();root.remove();resolve(value)};
    };

    const openManager=()=>{
      const manager=document.createElement('div');manager.className='modal-backdrop';
      const draw=()=>{
        const groups=[...new Set(catalog.map(row=>row.group_name))];
        manager.innerHTML=`<div class="modal-panel"><div class="modal-head"><div><h2>청산 항목 관리</h2><p class="sub">항목을 숨기거나 삭제해도 과거 거래에 저장된 청산 기록은 유지됩니다.</p></div><button class="btn ghost" data-manager-close>닫기</button></div><div class="modal-body"><form data-add-reason><div class="row"><label>분류<input name="group" list="exitReasonGroups" required placeholder="예: 계획된 청산"></label><label>새 청산 항목<input name="label" required placeholder="예: 목표가 일부 도달"></label></div><datalist id="exitReasonGroups">${groups.map(group=>`<option value="${esc(group)}">`).join('')}</datalist><button class="btn" type="submit">항목 추가</button></form><div class="strategy-manager-list">${catalog.map(row=>`<div class="mini-stat"><span><strong>${esc(row.label)}</strong><br><small>${esc(row.group_name)}${row.active?'':' · 숨김'}</small></span><span style="display:flex;gap:8px"><button class="btn ghost" type="button" data-exit-reason="${row.id}" data-active="${row.active?0:1}">${row.active?'표시에서 숨기기':'다시 표시'}</button><button class="btn ghost" type="button" data-delete-exit-reason="${row.id}" data-label="${esc(row.label)}">삭제</button></span></div>`).join('')}</div></div></div>`;
        manager.querySelector('[data-manager-close]').onclick=()=>manager.remove();
        manager.querySelector('[data-add-reason]').onsubmit=async event=>{event.preventDefault();try{const current=readForm(),payload=Object.fromEntries(new FormData(event.currentTarget));await request('/api/exit-reasons',{method:'POST',body:JSON.stringify(payload)});catalog=await request('/api/exit-reasons');draw();render(current)}catch(error){alert(error.message)}};
        manager.querySelectorAll('[data-exit-reason]').forEach(button=>button.onclick=async()=>{try{const current=readForm();await request(`/api/exit-reasons/${button.dataset.exitReason}`,{method:'PATCH',body:JSON.stringify({active:button.dataset.active==='1'})});catalog=await request('/api/exit-reasons');draw();render(current)}catch(error){alert(error.message)}});
        manager.querySelectorAll('[data-delete-exit-reason]').forEach(button=>button.onclick=async()=>{if(!confirm(`'${button.dataset.label}' 청산 항목을 삭제할까요? 과거 거래 기록은 유지됩니다.`))return;try{const current=readForm();await request(`/api/exit-reasons/${button.dataset.deleteExitReason}`,{method:'DELETE'});catalog=await request('/api/exit-reasons');draw();render(current)}catch(error){alert(error.message)}});
      };
      draw();document.body.append(manager);
    };

    root.addEventListener('click',event=>{if(event.target===root){root.remove();resolve(null)}});
    const start=async()=>{if(!catalog.length)catalog=await request('/api/exit-reasons');render();document.body.append(root)};
    start().catch(error=>{alert(error.message);resolve(null)});
  });
}

window.InvestmentBetaExit={open};
