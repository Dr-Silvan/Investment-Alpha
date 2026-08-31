export function install({api,toast}) {
  const guideUrl='https://app.alpaca.markets/signup';
  const relabel=root=>{const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);let node;while(node=walker.nextNode()){node.nodeValue=node.nodeValue.replaceAll('Yahoo Finance','Alpaca historical SIP').replace('Market data connector is not configured yet.','Market data: Alpaca historical SIP')}};
  new MutationObserver(records=>records.forEach(record=>record.addedNodes.forEach(node=>{if(node.nodeType===Node.ELEMENT_NODE)relabel(node)}))).observe(document.body,{childList:true,subtree:true});
  async function status(){return api('/api/provider-settings')}
  async function open(force=false){
    const current=await status();
    if(current.configured&&!force)return current;
    document.querySelector('.provider-modal')?.remove();
    const modal=document.createElement('div');
    modal.className='modal-backdrop provider-modal';
    modal.innerHTML=`<div class="modal-panel"><div class="modal-head"><div><h2>시장 데이터 연결</h2><p class="sub">Alpaca historical SIP · 미국 전체 거래소 완료 일봉</p></div><button class="btn ghost" type="button" data-close>나중에</button></div><div class="modal-body"><div class="result-stack"><div class="result-row"><span>1</span><strong>Alpaca 무료 계정 만들기</strong></div><div class="result-row"><span>2</span><strong>Paper Trading의 API Keys 열기</strong></div><div class="result-row"><span>3</span><strong>Key ID와 Secret Key를 아래에 붙여넣기</strong></div></div><p class="modal-copy">무료 Basic 계정도 장 종료 15분이 지난 historical SIP 일봉을 조회할 수 있습니다. Secret은 생성 화면에서 다시 보이지 않을 수 있으므로 즉시 복사하세요.</p><p><a class="source-link" href="${guideUrl}" target="_blank" rel="noopener noreferrer">Alpaca 계정 만들기 ↗</a></p><form id="providerForm"><label>API Key ID<input name="apiKey" autocomplete="off" required></label><label>Secret Key<input name="apiSecret" type="password" autocomplete="new-password" required></label><div class="validation">키는 이 Windows 사용자만 해독할 수 있도록 DPAPI로 암호화되며 Git이나 투자 DB에 저장되지 않습니다.</div><button class="btn" type="submit">연결 확인 후 저장</button></form>${current.configured?'<button class="btn ghost" type="button" data-remove>저장된 연결 제거</button>':''}</div></div>`;
    document.body.appendChild(modal);
    modal.querySelector('[data-close]').onclick=()=>modal.remove();
    modal.querySelector('#providerForm').onsubmit=async event=>{event.preventDefault();const button=event.submitter;button.disabled=true;button.textContent='SPY 일봉으로 연결 확인 중…';try{await api('/api/provider-settings',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(event.currentTarget)))});modal.remove();toast('Alpaca historical SIP 연결을 저장했습니다.')}catch(error){toast(error.message);button.disabled=false;button.textContent='연결 확인 후 저장'}};
    const remove=modal.querySelector('[data-remove]');if(remove)remove.onclick=async()=>{await api('/api/provider-settings',{method:'DELETE'});modal.remove();toast('시장 데이터 연결을 제거했습니다.')};
    return current;
  }
  return {status,open};
}
