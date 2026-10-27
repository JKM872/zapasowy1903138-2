// ============================================================================
// TeamLogo – Avatar with team badge or initials fallback.
// The image comes from the backend (`media` = homeMedia/awayMedia, or a plain
// `badgeUrl`); there are no browser calls to TheSportsDB. Wikimedia images
// carry a small info link with author and license (attribution required).
// ============================================================================
'use client'

import { useState } from 'react'
import { Info } from 'lucide-react'
import { cn } from '@/lib/utils'
import { getTeamInitials, getTeamColor } from '@/lib/team-logos'
import type { MediaInfo } from '@/lib/types'

interface Props {
  name: string
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl'
  className?: string
  /** Backend media record (preferred). */
  media?: MediaInfo | null
  /** Pre-resolved badge URL from the backend (used when no media record). */
  badgeUrl?: string
}

const SIZES = {
  xs: 'h-5 w-5 text-[8px]',
  sm: 'h-7 w-7 text-[10px]',
  md: 'h-9 w-9 text-xs',
  lg: 'h-12 w-12 text-sm',
  xl: 'h-16 w-16 text-base',
}

/** "Photo: author, license" for Wikimedia Commons files, else null. */
export function mediaCreditText(media?: MediaInfo | null): string | null {
  if (!media || media.source !== 'wikimedia') return null
  const parts = [media.author || 'Unknown author', media.license].filter(Boolean)
  return `Photo: ${parts.join(', ')}`
}

/** Small info link to the Commons file page, overlaid on the avatar corner. */
export function MediaCredit({ media, large }: { media?: MediaInfo | null; large?: boolean }) {
  const text = mediaCreditText(media)
  if (!text || !media?.attributionUrl) return null
  return (
    <a
      href={media.attributionUrl}
      target="_blank"
      rel="noopener noreferrer"
      title={text}
      aria-label={`${text} (opens Wikimedia Commons)`}
      onClick={e => e.stopPropagation()}
      className={cn(
        'absolute -bottom-0.5 -right-0.5 z-10 flex items-center justify-center rounded-full',
        'bg-background/90 text-muted-foreground ring-1 ring-border hover:text-foreground',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary',
        large ? 'h-4 w-4' : 'h-3 w-3',
      )}
    >
      <Info className={large ? 'h-3 w-3' : 'h-2.5 w-2.5'} aria-hidden="true" />
    </a>
  )
}

export function TeamLogo({ name, size = 'md', className, media, badgeUrl }: Props) {
  const logoUrl = media?.url || badgeUrl || null
  const [failedUrl, setFailedUrl] = useState<string | null>(null)
  const initials = getTeamInitials(name)
  const color = getTeamColor(name)
  const sizeClass = SIZES[size]

  if (logoUrl && failedUrl !== logoUrl) {
    return (
      <div className={cn('relative shrink-0', sizeClass)}>
        <div className={cn('h-full w-full rounded-full overflow-hidden bg-muted', className)}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={logoUrl}
            alt={`${name} logo`}
            className="h-full w-full object-contain p-0.5"
            onError={() => setFailedUrl(logoUrl)}
            loading="lazy"
            referrerPolicy="no-referrer"
          />
        </div>
        <MediaCredit media={media} large={size === 'lg' || size === 'xl'} />
      </div>
    )
  }

  // Fallback: initials circle
  return (
    <div
      className={cn(
        'shrink-0 rounded-full flex items-center justify-center font-bold text-white select-none',
        sizeClass,
        className,
      )}
      style={{ backgroundColor: color }}
      title={name}
    >
      {initials}
    </div>
  )
}
