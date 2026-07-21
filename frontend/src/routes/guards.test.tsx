import { screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { renderApp } from '../test/render'
import { loginTargetForRole, RequireRole } from './guards'
vi.mock('../auth/AuthContext',()=>({useAuth:()=>({user:{id:1,role:'citizen',display_name:'市民'},loading:false})}))
describe('RequireRole',()=>{it('blocks users without the requested role',()=>{renderApp(<MemoryRouter initialEntries={['/admin']}><Routes><Route path="/forbidden" element={<div>无权访问</div>}/><Route element={<RequireRole roles={['admin']}/>}><Route path="/admin" element={<div>管理后台</div>}/></Route></Routes></MemoryRouter>);expect(screen.getByText('无权访问')).toBeInTheDocument();expect(screen.queryByText('管理后台')).not.toBeInTheDocument()})})
describe('loginTargetForRole',()=>{
  it('drops a stale route from the previous account role',()=>{expect(loginTargetForRole('citizen','/admin/audit')).toBe('/citizen/chat')})
  it('keeps a requested route that belongs to the new account role',()=>{expect(loginTargetForRole('admin','/admin/audit')).toBe('/admin/audit')})
})
