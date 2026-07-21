import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderApp } from '../test/render'
import { SlaStatus } from './SlaStatus'

describe('SlaStatus',()=>{
  it('shows an overdue duration',()=>{renderApp(<SlaStatus state="overdue" remainingSeconds={-3660}/>);expect(screen.getByLabelText('SLA 已超时')).toHaveTextContent('超出 61 分钟')})
  it('does not show a changing countdown while paused',()=>{renderApp(<SlaStatus state="paused" remainingSeconds={600}/>);expect(screen.getByLabelText('SLA 计时暂停')).toHaveTextContent('计时暂停');expect(screen.queryByText(/剩余/)).not.toBeInTheDocument()})
})
