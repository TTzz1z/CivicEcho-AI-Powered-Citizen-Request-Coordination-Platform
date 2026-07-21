import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { Spin } from 'antd'
import { useAuth } from '../auth/AuthContext'
import type { Role } from '../types'
export const roleHome:Record<Role,string>={citizen:'/citizen/chat',agent:'/agent/tickets',department_staff:'/department/tickets',admin:'/admin/dashboard'}
const rolePathPrefix:Record<Role,string>={citizen:'/citizen',agent:'/agent',department_staff:'/department',admin:'/admin'}
export function loginTargetForRole(role:Role,requestedPath?:string){const prefix=rolePathPrefix[role];return requestedPath&&(requestedPath===prefix||requestedPath.startsWith(`${prefix}/`))?requestedPath:roleHome[role]}
export function RequireAuth(){const {user,loading}=useAuth();const location=useLocation();if(loading)return <div style={{minHeight:'70vh',display:'grid',placeItems:'center'}}><Spin size="large"/></div>;return user?<Outlet/>:<Navigate to="/login" replace state={{from:location}}/>}
export function RequireRole({roles}:{roles:Role[]}){const {user}=useAuth();return user&&roles.includes(user.role)?<Outlet/>:<Navigate to="/forbidden" replace/>}
export function HomeRedirect(){const {user,loading}=useAuth();if(loading)return <Spin/>;return <Navigate to={user?roleHome[user.role]:'/welcome'} replace/>}
