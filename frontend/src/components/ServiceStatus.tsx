import { Alert } from 'antd'
import { useQuery } from '@tanstack/react-query'

async function probe(url:string){const response=await fetch(url,{signal:AbortSignal.timeout(4_000)});if(!response.ok)throw new Error(String(response.status));return true}
export function ServiceStatus(){
  const query=useQuery({queryKey:['service-status'],queryFn:async()=>{const [backend,rasa]=await Promise.allSettled([probe('/api/v1/system/health'),probe('/rasa/status')]);return {backend:backend.status==='fulfilled',rasa:rasa.status==='fulfilled'}},refetchInterval:30_000,retry:false})
  if(query.isLoading||(query.data?.backend&&query.data.rasa))return null
  const unavailable=[];if(!query.data?.backend)unavailable.push('工单服务');if(!query.data?.rasa)unavailable.push('智能对话服务')
  return <Alert role="status" banner showIcon type="warning" message={`${unavailable.join('、')}当前不可用`} description="页面会自动重试；未确认成功前请勿重复提交。"/>
}
