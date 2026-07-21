import { useEffect, useRef, useState } from 'react'
import { Empty, Spin } from 'antd'
import type { EChartsCoreOption } from 'echarts/core'

export function ChartPanel({option,label,empty=false}:{option:EChartsCoreOption;label:string;empty?:boolean}){
  const ref=useRef<HTMLDivElement>(null); const [loading,setLoading]=useState(true)
  useEffect(()=>{
    if(!ref.current||empty){setLoading(false);return}
    let disposed=false; let chart:{setOption:(value:EChartsCoreOption)=>void;resize:()=>void;dispose:()=>void}|undefined
    const load=async()=>{
      const {echarts:core}=await import('../charts/runtime')
      if(disposed||!ref.current)return
      chart=core.init(ref.current);chart.setOption(option);setLoading(false)
    }
    void load(); const resize=()=>chart?.resize(); window.addEventListener('resize',resize)
    return()=>{disposed=true;window.removeEventListener('resize',resize);chart?.dispose()}
  },[option,empty])
  if(empty)return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无可展示数据"/>
  return <div style={{position:'relative'}}>{loading&&<div className="chart-loading"><Spin tip="图表加载中"/></div>}<div ref={ref} className="chart" role="img" aria-label={label}/></div>
}
