import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { authApi, type User } from './api'

type AuthValue = {user: User | null; loading: boolean; signIn: (email:string,password:string)=>Promise<User>; signOut:()=>Promise<void>}
const AuthContext = createContext<AuthValue | null>(null)

const demoUser: User = {type:'user', id:1, username:'demo', email:'demo@example.invalid', memberships:[{organization_id:'demo',organization:'Demo workspace',role:'admin'}]}

export function AuthProvider({children}:{children:React.ReactNode}) {
  const demo = import.meta.env.VITE_DEMO_MODE === 'true'
  const [user,setUser] = useState<User|null>(demo ? demoUser : null)
  const [loading,setLoading] = useState(!demo)
  useEffect(() => { if (!demo) authApi.me().then(setUser).catch(()=>setUser(null)).finally(()=>setLoading(false)) }, [demo])
  const value = useMemo<AuthValue>(() => ({
    user, loading,
    signIn: async (email,password) => { const next = demo ? demoUser : await authApi.signIn(email,password); setUser(next); return next },
    signOut: async () => { if (!demo) await authApi.signOut(); setUser(null) },
  }), [user,loading,demo])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() { const value=useContext(AuthContext); if(!value) throw new Error('AuthProvider missing'); return value }
