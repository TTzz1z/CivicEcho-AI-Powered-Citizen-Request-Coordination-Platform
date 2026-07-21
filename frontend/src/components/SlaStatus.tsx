import { Tag } from 'antd'

const labels={on_track:'时限正常',due_soon:'即将超时',overdue:'已超时',paused:'计时暂停'} as const
const colors={on_track:'success',due_soon:'warning',overdue:'error',paused:'default'} as const

export function SlaStatus({state,remainingSeconds}:{state:keyof typeof labels;remainingSeconds?:number|null}){
  const minutes=remainingSeconds==null?null:Math.ceil(Math.abs(remainingSeconds)/60)
  return <Tag color={colors[state]} aria-label={`SLA ${labels[state]}`}>{labels[state]}{minutes!==null&&state!=='paused'?` · ${remainingSeconds!<0?'超出':'剩余'} ${minutes} 分钟`:''}</Tag>
}
