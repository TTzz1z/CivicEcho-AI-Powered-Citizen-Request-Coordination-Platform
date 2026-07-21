import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ApiError } from '../api/client'
import { renderApp } from '../test/render'
import { ErrorState } from './ErrorState'
describe('ErrorState',()=>{it('renders a safe service error without stack details',()=>{renderApp(<ErrorState error={new ApiError(500,'INTERNAL_ERROR','服务暂时不可用')}/>);expect(screen.getByText('服务暂时不可用')).toBeInTheDocument();expect(document.body.textContent).not.toContain('INTERNAL_ERROR')})})
