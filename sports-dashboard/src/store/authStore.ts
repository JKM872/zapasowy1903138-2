// ============================================================================
// Auth Store — Zustand store for Supabase auth state
// ============================================================================
'use client'

import { create } from 'zustand'
import { supabase } from '@/lib/supabase'
import type { User, Session } from '@supabase/supabase-js'

interface AuthState {
  user: User | null
  session: Session | null
  loading: boolean
  initialized: boolean

  init: () => Promise<void>
  signIn: (email: string, password: string) => Promise<{ error: string | null }>
  signUp: (email: string, password: string) => Promise<{ error: string | null }>
  signInWithGoogle: () => Promise<{ error: string | null }>
  signOut: () => Promise<void>

  /** Convenience: returns Bearer token or empty string */
  getToken: () => string
}

/** Map raw Supabase OAuth errors to a friendly English message */
export function friendlyOAuthError(raw?: string | null): string {
  const msg = (raw ?? '').toLowerCase()
  if (msg.includes('provider is not enabled') || msg.includes('unsupported provider')) {
    return 'Google sign-in is not enabled yet. Please use email and password for now.'
  }
  return 'Google sign-in failed. Please try again or use email and password.'
}

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  session: null,
  loading: true,
  initialized: false,

  init: async () => {
    if (get().initialized) return
    if (!supabase) {
      set({ loading: false, initialized: true })
      return
    }

    // Get current session
    const { data } = await supabase.auth.getSession()
    set({
      user: data.session?.user ?? null,
      session: data.session ?? null,
      loading: false,
      initialized: true,
    })

    // Listen for auth changes
    supabase.auth.onAuthStateChange((_event, session) => {
      set({ user: session?.user ?? null, session })
    })
  },

  signIn: async (email, password) => {
    if (!supabase) return { error: 'Supabase not configured' }
    set({ loading: true })
    const { error } = await supabase.auth.signInWithPassword({ email, password })
    set({ loading: false })
    return { error: error?.message ?? null }
  },

  signUp: async (email, password) => {
    if (!supabase) return { error: 'Supabase not configured' }
    set({ loading: true })
    const { error } = await supabase.auth.signUp({
      email,
      password,
      options: { emailRedirectTo: window.location.origin },
    })
    set({ loading: false })
    return { error: error?.message ?? null }
  },

  signInWithGoogle: async () => {
    if (!supabase) return { error: 'Sign-in is not available right now. Please try again later.' }
    set({ loading: true })
    const { data, error } = await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo: window.location.origin, skipBrowserRedirect: true },
    })
    if (error || !data?.url) {
      set({ loading: false })
      return { error: friendlyOAuthError(error?.message) }
    }
    // Preflight: a disabled provider answers 400 JSON instead of redirecting to Google
    try {
      const res = await fetch(data.url, { redirect: 'manual' })
      if (res.type !== 'opaqueredirect' && !res.ok) {
        const body = await res.text().catch(() => '')
        set({ loading: false })
        return { error: friendlyOAuthError(body) }
      }
    } catch {
      // Network/CORS issue on preflight: fall through and let the browser try
    }
    window.location.assign(data.url)
    return { error: null }
  },

  signOut: async () => {
    if (!supabase) return
    await supabase.auth.signOut()
    set({ user: null, session: null })
  },

  getToken: () => {
    const session = get().session
    return session?.access_token ? `Bearer ${session.access_token}` : ''
  },
}))
