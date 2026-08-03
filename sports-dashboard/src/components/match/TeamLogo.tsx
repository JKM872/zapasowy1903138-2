// ============================================================================
// TeamLogo – Avatar with team badge or initials fallback
// ============================================================================
'use client'

import { useState, useEffect } from 'react'
import { cn } from '@/lib/utils'
import { getTeamLogoUrl, getTeamInitials, getTeamColor } from '@/lib/team-logos'

interface Props {
  name: string
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl'
  className?: string
  /** Pre-resolved badge URL from the backend (preferred over client-side fetch). */
  badgeUrl?: string
}

const SIZES = {
  xs: 'h-5 w-5 text-[8px]',
  sm: 'h-7 w-7 text-[10px]',
  md: 'h-9 w-9 text-xs',
  lg: 'h-12 w-12 text-sm',
  xl: 'h-16 w-16 text-base',
}

export function TeamLogo({ name, size = 'md', className, badgeUrl }: Props) {
  const [fetchedUrl, setFetchedUrl] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (badgeUrl) return
    let cancelled = false
    getTeamLogoUrl(name).then(url => {
      if (!cancelled && url) setFetchedUrl(url)
    })
    return () => { cancelled = true }
  }, [name, badgeUrl])

  const logoUrl = badgeUrl || fetchedUrl
  const initials = getTeamInitials(name)
  const color = getTeamColor(name)
  const sizeClass = SIZES[size]

  if (logoUrl && !failed) {
    return (
      <div className={cn('relative shrink-0 rounded-full overflow-hidden bg-muted', sizeClass, className)}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={logoUrl}
          /* Decorative: the team name is always rendered next to the badge, so
             an alt here would make screen readers announce it twice. */
          alt=""
          className="h-full w-full object-contain p-0.5"
          onError={() => setFailed(true)}
          loading="lazy"
        />
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
