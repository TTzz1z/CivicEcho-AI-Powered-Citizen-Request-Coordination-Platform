import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import type { KbCitation } from '../types'
import { filterDisplayCitations, isCompleteCitation, PolicyCitations } from './PolicyCitations'

const complete: KbCitation = {
  index: 1,
  doc_id: 9,
  title: '路灯维修办法',
  doc_number: '市政发〔2024〕1号',
  issuing_authority: '市政管理处',
  excerpt: '市民可通过12345报修路灯故障。',
  is_expired: false,
}

describe('PolicyCitations helpers', () => {
  it('requires title + (doc_number or authority) + excerpt', () => {
    expect(isCompleteCitation(complete)).toBe(true)
    expect(isCompleteCitation({ ...complete, excerpt: '' })).toBe(false)
    expect(isCompleteCitation({ ...complete, doc_number: undefined, issuing_authority: undefined, department: undefined })).toBe(false)
  })

  it('returns empty list when no_evidence', () => {
    expect(filterDisplayCitations([complete], true)).toEqual([])
    expect(filterDisplayCitations([complete], false)).toHaveLength(1)
  })

  it('omits expired evidence', () => {
    expect(filterDisplayCitations([{ ...complete, is_expired: true }], false)).toEqual([])
    expect(filterDisplayCitations([{ ...complete, expires_at: '2001-01-01T00:00:00Z' }], false)).toEqual([])
    expect(filterDisplayCitations([{ ...complete, status: 'WITHDRAWN' }], false)).toEqual([])
  })
})

describe('PolicyCitations UI', () => {
  it('renders nothing for no_evidence even with fake citations', () => {
    const { container } = render(
      <MemoryRouter>
        <PolicyCitations citations={[complete]} noEvidence />
      </MemoryRouter>,
    )
    expect(container).toBeEmptyDOMElement()
    expect(screen.queryByTestId('policy-citations')).not.toBeInTheDocument()
  })

  it('opens the cited evidence in place for a visitor', async () => {
    render(
      <MemoryRouter>
        <PolicyCitations citations={[complete]} />
      </MemoryRouter>,
    )
    expect(screen.getByTestId('policy-citations')).toBeInTheDocument()
    expect(screen.getByText('路灯维修办法')).toBeInTheDocument()
    expect(screen.getByText('市政发〔2024〕1号')).toBeInTheDocument()
    expect(screen.getByText('市政管理处')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /路灯维修办法/ }))
    await userEvent.click(screen.getByRole('button', { name: '查看详情：路灯维修办法' }))
    const details = await screen.findByRole('dialog', { name: '路灯维修办法' })
    expect(within(details).getByText(complete.excerpt!)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '查看详情' })).not.toBeInTheDocument()
  })
})
