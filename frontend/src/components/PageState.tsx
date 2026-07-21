import { Empty, Spin } from 'antd'

export function PageLoading({label='页面加载中'}:{label?:string}){return <div style={{minHeight:'50vh',display:'grid',placeItems:'center'}} role="status" aria-live="polite"><Spin size="large" tip={label}/></div>}
export function EmptyState({description='暂无数据'}:{description?:string}){return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={description}/>} 
