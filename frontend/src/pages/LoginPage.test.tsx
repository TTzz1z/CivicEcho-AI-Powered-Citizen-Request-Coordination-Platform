import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { renderApp } from '../test/render'
import { LoginPage } from './LoginPage'
vi.mock('../auth/AuthContext',()=>({useAuth:()=>({refresh:vi.fn(),user:null})}))
vi.mock('../api/auth',()=>({login:vi.fn()}))
describe('LoginPage',()=>{it('validates required credentials',async()=>{renderApp(<MemoryRouter><LoginPage/></MemoryRouter>);await userEvent.click(screen.getByRole('button',{name:'安全登录'}));expect(await screen.findByText('请输入用户名')).toBeInTheDocument();expect(screen.getByText('请输入密码')).toBeInTheDocument();await new Promise(resolve=>setTimeout(resolve,30))})})
