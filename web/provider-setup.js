export function install({api,toast}) {
  const guideUrl='https://app.alpaca.markets/signup';
  let activeProvider='yfinance';
  const content=document.querySelector('#content');
  const relabel=root=>{if(activeProvider!=='alpaca')return;const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);let node;while(node=walker.nextNode())node.nodeValue=node.nodeValue.replaceAll('Yahoo Finance','Alpaca historical SIP')};
  new MutationObserver(records=>records.forEach(record=>record.addedNodes.forEach(node=>{if(node.nodeType===Node.ELEMENT_NODE)relabel(node)}))).observe(content,{childList:true,subtree:true});
  async function status(){const current=await api('/api/provider-settings');activeProvider=current.provider;relabel(content);return current}
  async function open(){
    const current=await status();
    document.querySelector('.provider-modal')?.remove();
    const modal=document.createElement('div');
    modal.className='modal-backdrop provider-modal';
    modal.innerHTML=`<div class="modal-panel"><div class="modal-head"><div><h2>시장 데이터 설정</h2><p class="sub">기본값은 별도 가입이 필요 없는 Yahoo Finance입니다.</p></div><button class="btn ghost" type="button" data-close>닫기</button></div><div class="modal-body"><div class="provider-choices"><label class="provider-choice ${current.provider==='yfinance'?'selected':''}"><input type="radio" name="providerChoice" value="yfinance" ${current.provider==='yfinance'?'checked':''}><span><strong>Yahoo Finance · yfinance</strong><small>추천 · API 키 없이 완료된 미국장 일봉 조회</small></span></label><label class="provider-choice ${current.provider==='alpaca'?'selected':''}"><input type="radio" name="providerChoice" value="alpaca" ${current.provider==='alpaca'?'checked':''}><span><strong>Alpaca historical SIP</strong><small>선택 사항 · 개인 API Key와 Secret 필요</small></span></label></div><section class="provider-note"><strong>현재 공급자</strong><span>${current.displayName}</span><p>가격은 투자 판단을 대신하지 않으며, 화면의 기준일을 항상 확인하세요.</p></section><form id="providerForm" class="${current.provider==='alpaca'?'':'is-hidden'}"><div class="row"><label>API Key ID<input name="apiKey" autocomplete="off"></label><label>Secret Key<input name="apiSecret" type="password" autocomplete="new-password"></label></div><div class="validation">키는 Windows DPAPI로 로컬 암호화되며 Git이나 투자 데이터베이스에 저장되지 않습니다.</div><p><a class="source-link" href="${guideUrl}" target="_blank" rel="noopener noreferrer">Alpaca 계정 및 API 키 발급 ↗</a></p></form></div><div class="modal-actions"><button class="btn" type="button" data-save>선택한 공급자 저장</button></div></div>`;
    document.body.appendChild(modal);
    const form=modal.querySelector('#providerForm');
    const sync=()=>{const value=modal.querySelector('[name="providerChoice"]:checked').value;form.classList.toggle('is-hidden',value!=='alpaca');modal.querySelectorAll('.provider-choice').forEach(x=>x.classList.toggle('selected',x.querySelector('input').checked))};
    modal.querySelectorAll('[name="providerChoice"]').forEach(x=>x.onchange=sync);
    modal.querySelector('[data-close]').onclick=()=>modal.remove();
    modal.querySelector('[data-save]').onclick=async event=>{const provider=modal.querySelector('[name="providerChoice"]:checked').value;const payload={provider};if(provider==='alpaca')Object.assign(payload,Object.fromEntries(new FormData(form)));event.currentTarget.disabled=true;event.currentTarget.textContent='연결 확인 중…';try{await api('/api/provider-settings',{method:'POST',body:JSON.stringify(payload)});modal.remove();toast(`${provider==='yfinance'?'Yahoo Finance':'Alpaca'}를 시장 데이터 공급자로 설정했습니다.`);setTimeout(()=>location.reload(),500)}catch(error){toast(error.message);event.currentTarget.disabled=false;event.currentTarget.textContent='선택한 공급자 저장'}};
    return current;
  }
  return {status,open};
}
