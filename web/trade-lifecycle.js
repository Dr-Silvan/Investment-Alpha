export function install(ctx){
  const {state,viewOverrides,$,api,money,toast,load}=ctx;
  queueMicrotask(()=>{
    const base=viewOverrides.positions;
    viewOverrides.positions=()=>{
      base();
      [...document.querySelectorAll('section.card')].find(section=>section.querySelector('h2')?.textContent==='계획 및 시스템 거래')?.remove();
      const planned=state.data.planned||[],active=state.data.active||[],closed=(state.data.recent||[]).filter(x=>x.status==='closed');
      const row=(trade,action)=>`<tr><td class="ticker">${trade.ticker}</td><td><span class="badge ${trade.status==='active'?'green':''}">${trade.status}</span></td><td class="mono">$${money(trade.entry)}</td><td class="mono">${money(trade.quantity)}</td><td class="mono">1 : ${trade.rr.toFixed(2)}</td><td class="mono">${trade.realized_pnl==null?'—':`${trade.realized_pnl>=0?'+':''}$${money(trade.realized_pnl)}`}</td><td>${action}</td></tr>`;
      $('#content').insertAdjacentHTML('beforeend',`<section class="card" style="margin-top:18px"><div class="card-head"><div><h2>Trade execution</h2><p class="sub">계획을 실제 거래로 전환하고 종료 손익을 자산 원장에 자동 반영합니다.</p></div></div>${planned.length||active.length||closed.length?`<table><thead><tr><th>Ticker</th><th>Status</th><th>Entry</th><th>Quantity</th><th>R:R</th><th>Realized P&L</th><th></th></tr></thead><tbody>${planned.map(t=>row(t,`<button class="btn activate-trade" data-id="${t.id}">실행 시작</button>`)).join('')}${active.map(t=>row(t,`<button class="btn close-trade" data-id="${t.id}" data-ticker="${t.ticker}" data-entry="${t.entry}">종료 기록</button>`)).join('')}${closed.map(t=>row(t,'완료')).join('')}</tbody></table>`:'<div class="empty"><strong>거래 계획이 없습니다.</strong>Trade planner에서 새 거래를 만드세요.</div>'}</section>`);
      document.querySelectorAll('.activate-trade').forEach(button=>button.onclick=async()=>{try{await api(`/api/trades/${button.dataset.id}`,{method:'PATCH',body:JSON.stringify({status:'active'})});await load();toast('거래를 활성 포지션으로 전환했습니다.');viewOverrides.positions()}catch(error){toast(error.message)}});
      document.querySelectorAll('.close-trade').forEach(button=>button.onclick=async()=>{const review=await window.InvestmentBetaExit.open({ticker:button.dataset.ticker,defaultPrice:button.dataset.entry});if(!review)return;try{await api(`/api/trades/${button.dataset.id}`,{method:'PATCH',body:JSON.stringify({status:'closed',...review})});await load();toast('종료 손익과 매도 근거를 저장했습니다.');viewOverrides.positions()}catch(error){toast(error.message)}});
    };
  });
}
