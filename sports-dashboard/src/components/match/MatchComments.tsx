// ============================================================================
// MatchComments – reader-contributed context for one event
// ============================================================================
'use client'

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MessageSquare, Trash2, Loader2, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { addComment, deleteComment, getComments, type MatchComment } from '@/lib/api'
import { useAuthStore } from '@/store/authStore'

const MAX_LEN = 1000

interface Props {
  matchId: string | number
}

/**
 * Comments carry what the model cannot see — a missing first-choice setter, a
 * table moved indoors, a player who landed the same morning. Reading is open;
 * posting needs an account so a claim always has an author behind it.
 */
export function MatchComments({ matchId }: Props) {
  const user = useAuthStore(s => s.user)
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState('')

  const key = ['comments', String(matchId)]
  const { data, isLoading, isError } = useQuery({
    queryKey: key,
    queryFn: () => getComments(matchId),
    staleTime: 30_000,
  })

  const post = useMutation({
    mutationFn: () =>
      addComment(matchId, draft.trim(), user?.email?.split('@')[0] ?? undefined),
    onSuccess: () => {
      setDraft('')
      queryClient.invalidateQueries({ queryKey: key })
    },
  })

  const remove = useMutation({
    mutationFn: (id: number) => deleteComment(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: key }),
  })

  const comments = data?.comments ?? []
  const remaining = MAX_LEN - draft.length
  const tooLong = remaining < 0
  const canPost = !!user && draft.trim().length > 0 && !tooLong && !post.isPending

  return (
    <div className="space-y-3 rounded-md border border-border bg-card p-4">
      <div className="flex items-center gap-2 text-sm font-medium">
        <MessageSquare className="h-4 w-4 text-sky-400" />
        Fan comments
        {comments.length > 0 && (
          <span className="text-xs tabular-nums text-muted-foreground">
            {comments.length}
          </span>
        )}
      </div>

      {/* The board has to work without a database, like everything else here. */}
      {data && !data.available && (
        <p className="text-xs text-muted-foreground">
          Comments are temporarily unavailable.
        </p>
      )}

      {isLoading && (
        <div className="flex justify-center py-3">
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        </div>
      )}

      {isError && (
        <p className="text-xs text-destructive">
          Couldn’t load comments.
        </p>
      )}

      {/* Composer */}
      {data?.available && (
        user ? (
          <div className="space-y-1.5">
            <textarea
              value={draft}
              onChange={e => setDraft(e.target.value)}
              rows={3}
              maxLength={MAX_LEN + 200}
              placeholder="What should others know about this event? Injuries, line-ups, conditions…"
              aria-label="Comment text"
              className={cn(
                'w-full resize-y rounded-md border bg-background p-2 text-sm',
                'placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring',
                tooLong ? 'border-destructive' : 'border-input',
              )}
            />
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  'text-[10px] tabular-nums',
                  tooLong ? 'text-destructive' : 'text-muted-foreground',
                )}
              >
                {remaining} characters left
              </span>
              <Button
                size="sm"
                className="ml-auto h-7"
                disabled={!canPost}
                onClick={() => post.mutate()}
              >
                {post.isPending && <Loader2 className="mr-1 h-3 w-3 animate-spin" />}
                Post comment
              </Button>
            </div>
            {post.isError && (
              <p className="flex gap-1.5 text-[11px] text-destructive">
                <TriangleAlert className="mt-px h-3 w-3 shrink-0" />
                {(post.error as Error)?.message?.includes('429')
                  ? 'Too many comments in a short time. Please wait a moment.'
                  : 'Couldn’t post your comment.'}
              </p>
            )}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">
            Sign in to comment.
          </p>
        )
      )}

      {/* Thread */}
      {!isLoading && comments.length === 0 && data?.available && (
        <p className="text-xs text-muted-foreground">
          No comments yet.
        </p>
      )}

      <ul className="space-y-2">
        {comments.map((c: MatchComment) => (
          <li key={c.id} className="rounded-md bg-panel p-2.5">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold">{c.author}</span>
              <time
                className="text-[10px] text-muted-foreground"
                dateTime={c.createdAt}
              >
                {formatWhen(c.createdAt)}
              </time>
              {c.isMine && (
                <button
                  onClick={() => remove.mutate(c.id)}
                  disabled={remove.isPending}
                  aria-label="Delete comment"
                  className="ml-auto rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              )}
            </div>
            <p className="mt-1 whitespace-pre-wrap break-words text-xs leading-relaxed">
              {c.body}
            </p>
          </li>
        ))}
      </ul>

      {comments.length > 0 && (
        <p className="border-t border-border/60 pt-2 text-[10px] leading-relaxed text-muted-foreground">
          Comments come from users and are not verified by us.
          They are not part of the model’s analysis.
        </p>
      )}
    </div>
  )
}

/** "2026-08-05T12:00:00+00:00" → "5 sie, 14:00" in the reader's timezone. */
function formatWhen(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString('en-GB', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}
