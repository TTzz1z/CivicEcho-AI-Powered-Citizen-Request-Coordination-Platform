import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderApp } from '../test/render'
import { TicketStatusTag } from './TicketStatusTag'
describe('TicketStatusTag',()=>{it('renders the Chinese status label',()=>{renderApp(<TicketStatusTag status="processing"/>);expect(screen.getByText('处理中')).toBeInTheDocument()})})
