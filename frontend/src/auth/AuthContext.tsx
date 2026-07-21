import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { getMe } from '../api/auth'
import { tokenStore } from '../api/client'
import type { User } from '../types'
import {
  clearChatPrivacyOnAccountSwitch,
  clearChatPrivacyStorage,
  clearChatPrivacyStorageAndBroadcast,
  subscribeChatPrivacyClear,
} from '../utils/chatStorage'

interface AuthState { user:User|null; loading:boolean; refresh:()=>Promise<User|null>; logout:()=>void }
const AuthContext=createContext<AuthState|null>(null)
export function AuthProvider({children}:{children:ReactNode}){
  const [user,setUser]=useState<User|null>(null); const [loading,setLoading]=useState(true)
  const previousUserId=useRef<number|undefined>(undefined)
  const refresh=async()=>{
    if(!tokenStore.get()){setUser(null);setLoading(false);return null}
    try{
      const next=await getMe()
      clearChatPrivacyOnAccountSwitch(previousUserId.current, next?.id)
      previousUserId.current=next?.id
      setUser(next)
      return next
    }catch{setUser(null);return null}
    finally{setLoading(false)}
  }
  const logout=()=>{
    clearChatPrivacyStorageAndBroadcast()
    previousUserId.current=undefined
    tokenStore.clear()
    setUser(null)
  }
  useEffect(()=>{
    void refresh()
    const unauthorized=()=>{
      clearChatPrivacyStorageAndBroadcast()
      previousUserId.current=undefined
      setUser(null)
    }
    window.addEventListener('tingting:unauthorized',unauthorized)
    const unsubscribe=subscribeChatPrivacyClear(()=>{
      // Other tab logged out — clear this tab's storage + session auth state.
      clearChatPrivacyStorage()
      previousUserId.current=undefined
      tokenStore.clear()
      setUser(null)
    })
    return()=>{
      window.removeEventListener('tingting:unauthorized',unauthorized)
      unsubscribe()
    }
  },[])
  return <AuthContext.Provider value={{user,loading,refresh,logout}}>{children}</AuthContext.Provider>
}
export function useAuth(){const value=useContext(AuthContext);if(!value)throw new Error('useAuth must be inside AuthProvider');return value}
