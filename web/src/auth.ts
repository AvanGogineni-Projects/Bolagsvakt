// Sign-in. With VITE_SUPABASE_URL + VITE_SUPABASE_PUBLISHABLE_KEY set (production), Supabase
// handles it: an emailed magic link, and a session the client refreshes on its own. Without
// them (local development), a dev login gets a token from the API's /v1/dev/token, which only
// exists when the API runs with BOLAGSVAKT_ENV=dev.
import { createClient } from '@supabase/supabase-js'
import { useEffect, useState } from 'react'

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined
const key = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY as string | undefined
export const supabase = url && key ? createClient(url, key) : null
export const devLogin = supabase === null

const DEV_TOKEN = 'bolagsvakt_dev_token'

export async function getToken(): Promise<string | null> {
  if (supabase) return (await supabase.auth.getSession()).data.session?.access_token ?? null
  return localStorage.getItem(DEV_TOKEN)
}

export function setDevToken(token: string) {
  localStorage.setItem(DEV_TOKEN, token)
}

export async function signOut() {
  localStorage.removeItem(DEV_TOKEN)
  if (supabase) await supabase.auth.signOut()
}

export async function sendMagicLink(email: string) {
  if (!supabase) throw new Error('Supabase is not configured')
  const { error } = await supabase.auth.signInWithOtp({ email, options: { emailRedirectTo: window.location.origin } })
  if (error) throw error
}

/** undefined while checking, then whether someone is signed in (and kept current). */
export function useSignedIn(): boolean | undefined {
  const [signedIn, setSignedIn] = useState<boolean | undefined>(undefined)
  useEffect(() => {
    getToken().then((t) => setSignedIn(t !== null))
    const sub = supabase?.auth.onAuthStateChange((_event, session) => setSignedIn(session !== null))
    return () => sub?.data.subscription.unsubscribe()
  }, [])
  return signedIn
}
