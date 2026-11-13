import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { User, UserManager } from 'oidc-client-ts'

const authority = import.meta.env.VITE_OIDC_AUTHORITY
const clientId = import.meta.env.VITE_OIDC_CLIENT_ID
const manager = authority && clientId ? new UserManager({
  authority, client_id: clientId, redirect_uri: `${window.location.origin}/auth/callback`,
  post_logout_redirect_uri: window.location.origin, response_type: 'code', scope: 'openid profile email',
}) : null

type AuthState = { user: User | null; token: string | null; loading: boolean; configured: boolean; login: () => Promise<void>; logout: () => Promise<void>; finishLogin: () => Promise<void> }
const Context = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(!!manager)
  useEffect(() => {
    if (!manager) return
    void manager.getUser().then(value => setUser(value && !value.expired ? value : null)).finally(() => setLoading(false))
    const onLoaded = (value: User) => setUser(value)
    const onUnloaded = () => setUser(null)
    manager.events.addUserLoaded(onLoaded)
    manager.events.addUserUnloaded(onUnloaded)
    return () => { manager.events.removeUserLoaded(onLoaded); manager.events.removeUserUnloaded(onUnloaded) }
  }, [])
  const login = useCallback(async () => { await manager?.signinRedirect() }, [])
  const logout = useCallback(async () => { if (manager) { await manager.removeUser(); await manager.signoutRedirect() } }, [])
  const finishLogin = useCallback(async () => { if (manager) setUser(await manager.signinRedirectCallback()) }, [])
  const value = useMemo(() => ({ user, token: user?.access_token ?? null, loading, configured: !!manager, login, logout, finishLogin }), [user, loading, login, logout, finishLogin])
  return <Context.Provider value={value}>{children}</Context.Provider>
}

export function useAuth(): AuthState {
  const state = useContext(Context)
  if (!state) throw new Error('AuthProvider is missing')
  return state
}
