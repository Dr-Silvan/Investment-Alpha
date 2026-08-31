const reasons={
  '계획된 청산':['목표가 도달','사전에 정한 R 도달','분할익절 계획','보유기간 만료','이벤트 전 계획 청산'],
  '가격 구조 훼손':['주요 지지선 이탈','HL → LL 전환','상승 추세선 이탈','Swing AVWAP 하향 이탈','돌파 구간 재진입','Lower High 형성','하락 패턴 확인'],
  '모멘텀·자금 흐름':['RSI 지지 붕괴','RSI 약세 다이버전스','스토캐스틱 데드크로스','CMF 하락','CMF 0선 이탈','거래량 동반 하락','Accumulation/Distribution 약화'],
  '시장·종목 환경':['QQQ·SPY 추세 훼손','섹터 상대강도 약화','종목 상대강도 약화','실적·이벤트 위험','시장 Regime 변화'],
  '심리·재량':['손실 공포','수익 반납 공포','확신 저하','근거 없는 불안','다른 종목을 사고 싶어서','너무 오래 보유한 느낌','규칙 외 재량 매도']
};

function open({ticker,defaultPrice}){
  return new Promise(resolve=>{
    const root=document.createElement('div');root.className='modal-backdrop';
    root.innerHTML=`<div class="modal-panel"><div class="modal-head"><div><h2>${ticker} Exit Review</h2><p class="sub">매도 당시 알 수 있었던 근거만 기록하세요.</p></div><button class="btn ghost" data-close>닫기</button></div><form id="exitReviewForm"><div class="modal-body"><div class="row"><label>종료가 (USD)<input name="exitPrice" type="number" step="0.01" value="${defaultPrice}" required></label><label>종료일<input name="closedAt" type="date" value="${new Date().toISOString().slice(0,10)}" required></label></div><div><p class="sub">이 매도는 사전에 정의한 규칙에 따른 것인가?</p><div class="rule-choice"><label><input type="radio" name="ruleBased" value="true" required> 예, 계획된 규칙</label><label><input type="radio" name="ruleBased" value="false" required> 아니오, 재량 판단</label></div></div>${Object.entries(reasons).map(([group,items],index)=>`<details class="reason-details" ${index===0?'open':''}><summary>${group}</summary><div class="chip-grid">${items.map(item=>`<label class="evidence-chip"><input type="checkbox" name="reason" data-group="${group}" value="${item}"><span>${item}</span></label>`).join('')}</div></details>`).join('')}<label>매도 메모<textarea name="note" placeholder="무엇이 바뀌어서 포지션을 종료했는가?"></textarea></label></div><div class="modal-actions"><button type="button" class="btn ghost" data-close>취소</button><button type="submit" class="btn">종료 기록 저장</button></div></form></div>`;
    document.body.append(root);
    const close=()=>{root.remove();resolve(null)};root.querySelectorAll('[data-close]').forEach(button=>button.onclick=close);
    root.addEventListener('click',event=>{if(event.target===root)close()});
    root.querySelector('form').onsubmit=event=>{event.preventDefault();const form=event.target,review={ruleBased:form.elements.ruleBased.value==='true',note:form.elements.note.value};form.querySelectorAll('input[name="reason"]:checked').forEach(input=>(review[input.dataset.group]??=[]).push(input.value));const value={exitPrice:+form.elements.exitPrice.value,closedAt:form.elements.closedAt.value,exitReview:review};root.remove();resolve(value)};
  });
}

window.InvestmentBetaExit={open};
