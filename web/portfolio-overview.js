export function install(ctx){
  const {viewOverrides,$,api,money}=ctx;
  const base=viewOverrides.analytics;
  viewOverrides.analytics=()=>{
    base();
    const anchor=document.querySelector('.grid.kpis');
    if(!anchor)return;
    anchor.insertAdjacentHTML('afterend',`<section class="card" id="overallPerformance" style="margin-bottom:18px"><div class="card-head"><div><h2>전체 수익률</h2><p class="sub">투자 최초 사용일부터 전체 자산과 SPY·QQQ의 확정 종가 수익률을 비교합니다.</p></div><button class="btn ghost" id="overallRefresh">다시 계산</button></div><div id="overallPerformanceBody" class="empty"><strong>전체 성과를 계산하는 중...</strong>온라인 시장 데이터를 불러옵니다.</div></section>`);
    const render=async()=>{
      const output=$('#overallPerformanceBody');
      if(!output)return;
      output.className='empty';output.innerHTML='<strong>전체 성과를 계산하는 중...</strong>';
      try{
        const result=await api('/api/portfolio-relative-performance');
        const p=result.portfolio;
        output.className='';
        output.innerHTML=`<div class="grid kpis">${metric('전체 자산',p.returnPct,`$${money(p.startValue)} → $${money(p.endValue)} · 최신 ${p.endDate}`)}${result.benchmarks.map(row=>row.error?`<div class="card kpi"><div class="kpi-label">${row.ticker}</div><div class="kpi-value">조회 실패</div><div class="kpi-foot">시장 데이터를 확인하세요</div></div>`:metric(row.ticker,row.returnPct,`${row.startDate} → ${row.lastDate} · 전체 자산 대비 ${signed(p.returnPct-row.returnPct)}%p`)).join('')}</div><p class="sub" style="margin-top:12px">프로그램 시작일 ${result.requestedStartDate} · 전체 자산 수익률은 입출금을 제외하고 활성 포지션을 최신 확정 종가로 평가합니다.${result.requestedStartDate!==p.startDate?` 자산 원장이 늦게 시작되어 ${p.startDate}부터 계산했습니다.`:''}${p.errors?.length?` 가격 조회 실패: ${p.errors.map(x=>x.ticker).join(', ')}`:''}</p>`;
      }catch(error){output.innerHTML=`<strong>전체 수익률을 계산할 수 없습니다.</strong>${error.message}`}
    };
    $('#overallRefresh').onclick=render;render();
  };
}

const signed=value=>`${value>=0?'+':''}${Number(value).toFixed(2)}`;
const metric=(label,value,foot)=>`<div class="card kpi"><div class="kpi-label">${label}</div><div class="kpi-value ${value>=0?'positive':'negative'}">${signed(value)}%</div><div class="kpi-foot">${foot}</div></div>`;
