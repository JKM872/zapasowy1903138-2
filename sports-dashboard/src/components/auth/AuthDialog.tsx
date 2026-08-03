// ============================================================================
// AuthDialog — login / register modal
// ============================================================================
'use client'

import { useState } from 'react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Loader2 } from 'lucide-react'
import { useAuthStore } from '@/store/authStore'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function AuthDialog({ open, onOpenChange }: Props) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const { signIn, signUp, loading } = useAuthStore()

  const handleSubmit = async () => {
    setError(null)
    setSuccess(null)
    if (!email || !password) {
      setError('Podaj adres e-mail i hasło')
      return
    }
    if (password.length < 6) {
      setError('Hasło musi mieć co najmniej 6 znaków')
      return
    }

    if (mode === 'login') {
      const { error: err } = await signIn(email, password)
      if (err) setError(err)
      else onOpenChange(false)
    } else {
      const { error: err } = await signUp(email, password)
      if (err) setError(err)
      else {
        setSuccess('Sprawdź skrzynkę i potwierdź adres e-mail.')
      }
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{mode === 'login' ? 'Zaloguj się' : 'Utwórz konto'}</DialogTitle>
        </DialogHeader>

        <div className="grid gap-4 py-2">
          <div className="space-y-1.5">
            <Label htmlFor="auth-email">Email</Label>
            <Input
              id="auth-email"
              type="email"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="auth-password">Hasło</Label>
            <Input
              id="auth-password"
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
            />
          </div>

          {error && <p className="text-xs text-destructive">{error}</p>}
          {success && <p className="text-xs text-emerald-600">{success}</p>}

          <Button onClick={handleSubmit} disabled={loading} className="w-full">
            {loading && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
            {mode === 'login' ? 'Zaloguj się' : 'Zarejestruj się'}
          </Button>

          <p className="text-xs text-center text-muted-foreground">
            {mode === 'login' ? (
              <>
                Nie masz konta?{' '}
                <button className="text-primary underline" onClick={() => { setMode('register'); setError(null); setSuccess(null) }}>
                  Zarejestruj się
                </button>
              </>
            ) : (
              <>
                Masz juz konto?{' '}
                <button className="text-primary underline" onClick={() => { setMode('login'); setError(null); setSuccess(null) }}>
                  Zaloguj się
                </button>
              </>
            )}
          </p>
        </div>
      </DialogContent>
    </Dialog>
  )
}
