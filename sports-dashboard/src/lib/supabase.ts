// ============================================================================
// Supabase Client — singleton for auth + realtime
// ============================================================================
import { createClient } from '@supabase/supabase-js'

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL ?? ''
const SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? ''

export const supabase =
  SUPABASE_URL && SUPABASE_ANON_KEY
    ? createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
        // Picks up the OAuth (Google) session from the URL after redirect back
        auth: { detectSessionInUrl: true, persistSession: true, autoRefreshToken: true },
      })
    : null
