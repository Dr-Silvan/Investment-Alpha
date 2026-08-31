const tone=classification=>classification.includes('Chicken')||classification.includes('이른')?'negative':classification.includes('잘 방어')||classification.includes('계획대로')?'positive':'';
const escapeHtml=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

export function install(ctx){
  const {viewOverrides,$,api,money,toast}=ctx;
  queueMicrotask(()=>{
    const base=viewOverrides.analytics;
    viewOverrides.analytics=()=>{
      base();
      $('#content').insertAdjacentHTML('beforeend',`<section class="card" id="exitQuality" style="margin-top:18px"><div class="card-head"><div><h2>Exit quality</h2><p class="sub">매도 당시 근거와 이후 1·5·10·20 거래일을 분리해 평가합니다.</p></div><button class="btn secondary" id="refreshExit">관찰 업데이트</button></div><div id="exitQualityBody" class="empty"><strong>Exit 데이터를 불러오는 중...</strong></div></section>`);
      const render=async()=>{
        try{
          const rows=await api('/api/exit-quality'),body=$('#exitQualityBody');
          if(!rows.length){body.className='empty';body.innerHTML='<strong>종료된 거래가 없습니다.</strong>거래 종료 시 Exit Review가 자동으로 시작됩니다.';return}
          const counts=rows.reduce((acc,row)=>(acc[row.classification]=(acc[row.classification]||0)+1,acc),{});
          body.className='';body.innerHTML=`<div class="chip-grid" style="margin-bottom:14px">${Object.entries(counts).map(([key,value])=>`<span class="badge ${tone(key)==='positive'?'green':''}">${key} ${value}</span>`).join('')}</div><div class="journal-list">${rows.map(row=>{const reasons=Object.entries(row.review||{}).filter(([key,value])=>Array.isArray(value)&&value.length).flatMap(([group,items])=>items.map(item=>`${group}: ${item}`));const horizons=row.postExit?.horizons||{};return `<details class="reason-details"><summary><span class="ticker">${row.ticker}</span> · ${row.closedAt} · <span class="${tone(row.classification)}">${row.classification}</span></summary><div style="padding:0 14px 14px"><div class="chip-grid" style="margin-bottom:12px"><span class="badge ${row.review?.ruleBased?'green':''}">${row.review?.ruleBased?'사전 규칙':'재량 매도'}</span>${reasons.map(reason=>`<span class="badge">${reason}</span>`).join('')}</div><table><thead><tr><th>1D</th><th>5D</th><th>10D</th><th>20D</th><th>Post-exit MFE</th><th>Post-exit MAE</th></tr></thead><tbody><tr>${['1','5','10','20'].map(day=>`<td class="mono ${horizons[day]?.returnPct>=0?'positive':'negative'}">${horizons[day]?`${horizons[day].returnPct>=0?'+':''}${horizons[day].returnPct.toFixed(2)}%`:'관찰 중'}</td>`).join('')}<td class="mono positive">${row.postExit?.mfePct==null?'—':`+${row.postExit.mfePct.toFixed(2)}%`}</td><td class="mono negative">${row.postExit?.maePct==null?'—':`${row.postExit.maePct.toFixed(2)}%`}</td></tr></tbody></table>${row.review?.note?`<p class="sub" style="margin-top:10px">매도 메모: ${escapeHtml(row.review.note)}</p>`:''}</div></details>`}).join('')}</div>`;
        }catch(error){$('#exitQualityBody').innerHTML=`<strong>Exit 데이터를 불러오지 못했습니다.</strong>${error.message}`}
      };
      const refresh=async()=>{const button=$('#refreshExit');button.disabled=true;button.textContent='업데이트 중...';try{const result=await api('/api/exit-observations/refresh',{method:'POST',body:'{}'});localStorage.setItem('exitRefreshDate',new Date().toISOString().slice(0,10));toast(`${result.updated}개 거래의 관찰 데이터를 갱신했습니다.`);await render()}catch(error){toast(error.message)}finally{button.disabled=false;button.textContent='관찰 업데이트'}};
      $('#refreshExit').onclick=refresh;render();
      const today=new Date().toISOString().slice(0,10);if(localStorage.getItem('exitRefreshDate')!==today)setTimeout(refresh,300);
    };
  });
}
