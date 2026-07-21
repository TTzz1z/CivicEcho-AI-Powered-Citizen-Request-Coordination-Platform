import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { getMe } from '../api/auth'
import { tokenStore } from '../api/client'
import type { User } from '../types'

interface AuthState { user:User|null; loading:boolean; refresh:()=>Promise<User|null>; logout:()=>void }
const AuthContext=createContext<AuthState|null>(null)
export function AuthProvider({children}:{children:ReactNode}){
  const [user,setUser]=useState<User|null>(null); const [loading,setLoading]=useState(true)
  const refresh=async()=>{if(!tokenStore.get()){setUser(null);setLoading(false);return null}try{const next=await getMe();setUser(next);return next}catch{setUser(null);return null}finally{setLoading(false)}}
  const logout=()=>{tokenStore.clear();setUser(null)}
  useEffect(()=>{void refresh();const unauthorized=()=>{setUser(null)};window.addEventListener('tingting:unauthorized',unauthorized);return()=>window.removeEventListener('tingting:unauthorized',unauthorized)},[])
  return <AuthContext.Provider value={{user,loading,refresh,logout}}>{children}</AuthContext.Provider>
}
export function useAuth(){const value=useContext(AuthContext);if(!value)throw new Error('useAuth must be inside AuthProvider');return value}
