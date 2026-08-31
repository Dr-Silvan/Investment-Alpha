export function install(ctx){
  const {viewOverrides,$,api}=ctx;
  const base=viewOverrides.positions;
  viewOverrides.positions=()=>{
    base();
    const heading=[...document.querySelectorAll('h2')].find(node=>node.textContent.trim()==='Benchmark relative performance');
    const section=heading?.closest('section');
    if(!section)return;
    section.innerHTML=`<div class="card-head"><div><h2>종목별 상대 수익률</h2><p class="sub">각 종목을 해당 핵심 섹터 ETF의 대표 대장주 및 SPY와 비교합니다.</p></div><button class="btn ghost" id="sectorBenchmarkRefresh">다시 계산</button></div><div id="sectorBenchmarkResults" class="empty"><strong>섹터와 시장 수익률을 계산하는 중...</strong>온라인 시장 데이터를 불러옵니다.</div>`;
    const render=async()=>{
      const output=$('#sectorBenchmarkResults');if(!output)return;
      output.className='empty';output.innerHTML='<strong>섹터와 시장 수익률을 계산하는 중...</strong>';
      try{
        const result=await api('/api/sector-relative-performance');
        if(!result.comparisons.length){output.innerHTML='<strong>비교할 포지션이 없습니다.</strong>';return}
        output.className='';
        output.innerHTML=`<table><thead><tr><th>Position</th><th>Since</th><th>Position return</th><th>Sector leader</th><th>SPY</th></tr></thead><tbody>${result.comparisons.map(row=>{
          const leader=row.benchmarks.find(item=>item.ticker!=='SPY'),spy=row.benchmarks.find(item=>item.ticker==='SPY');
          return `<tr><td class="ticker">${row.ticker}</td><td class="mono">${row.openedAt}</td><td>${performance(row.positionReturnPct)}</td><td>${row.profile.error?`<span class="negative">분류 필요</span><br><span class="sub">${row.profile.sector||row.profile.error}</span>`:benchmark(leader,`${row.profile.sector} · ${row.profile.sectorEtf} 대표`)}</td><td>${benchmark(spy,'미국 전체 시장')}</td></tr>`
        }).join('')}</tbody></table><p class="sub" style="margin-top:12px">Alpha는 포지션 수익률 − 비교 대상 수익률입니다. 섹터 대표주는 핵심 섹터 ETF의 대표 대형주로 배정됩니다.</p>`;
      }catch(error){output.innerHTML=`<strong>상대 수익률을 계산할 수 없습니다.</strong>${error.message}`}
    };
    $('#sectorBenchmarkRefresh').onclick=render;render();
  };
}

const performance=value=>`<span class="mono ${value>=0?'positive':'negative'}">${value>=0?'+':''}${Number(value).toFixed(2)}%</span>`;
const benchmark=(row,description)=>row&&!row.error?`<strong class="ticker">${row.ticker}</strong> ${performance(row.returnPct)}<br><span class="sub">${row.startDate} → ${row.lastDate} · Alpha ${row.alphaPct>=0?'+':''}${row.alphaPct.toFixed(2)}%p · ${description}</span>`:`<span class="negative">가격 조회 실패</span>`;
