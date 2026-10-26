// ============================================================================
// SideAvatar – round logo / player photo for one side of a match.
// Wraps TeamLogo for team sports; for individual sports (tennis, table tennis)
// renders a player avatar circle (photo when the API sends one, else initials).
// ============================================================================
'use client'
import { useState } from 'react'
import { cn } from '@/lib/utils'
import { getTeamInitials, getTeamColor } from '@/lib/team-logos'
import { TeamLogo } from './TeamLogo'
import type { Match, Sport } from '@/lib/types'

type Size = 'sm' | 'md' | 'lg' | 'xl'

const INDIVIDUAL_SPORTS: readonly Sport[] = ['tennis', 'table_tennis']

/** Fixed pixel boxes, so images never shift the layout while loading. */
const PX: Record<Size, number> = { sm: 28, md: 36, lg: 48, xl: 64 }
const TEXT: Record<Size, string> = {
  sm: 'text-[10px]', md: 'text-xs', lg: 'text-sm', xl: 'text-base',
}

export function isIndividualSport(sport: Sport): boolean {
  return INDIVIDUAL_SPORTS.includes(sport)
}

interface Props {
  match: Match
  side: 'home' | 'away'
  size?: Size
  className?: string
}

export function SideAvatar({ match, side, size = 'sm', className }: Props) {
  const name = side === 'home' ? match.homeTeam : match.awayTeam
  const logo = side === 'home' ? match.homeLogo : match.awayLogo
  const photo = side === 'home' ? match.homePhoto : match.awayPhoto

  if (!isIndividualSport(match.sport)) {
    return (
      <TeamLogo
        name={name}
        size={size}
        badgeUrl={photo || logo}
        className={cn('ring-1 ring-border', className)}
      />
    )
  }
  return <PlayerAvatar name={name} url={photo || logo} size={size} className={className} />
}

function PlayerAvatar({
  name, url, size, className,
}: { name: string; url?: string; size: Size; className?: string }) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null)
  const px = PX[size]
  const box = cn(
    'relative shrink-0 overflow-hidden rounded-full ring-1 ring-border',
    className,
  )
  if (url && failedUrl !== url) {
    return (
      <div className={cn(box, 'bg-muted')} style={{ width: px, height: px }}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={url}
          alt={name}
          width={px}
          height={px}
          loading="lazy"
          className="h-full w-full object-cover object-top"
          onError={() => setFailedUrl(url)}
        />
      </div>
    )
  }
  // Initials on a tinted circle with a ring, styled as a person avatar.
  return (
    <div
      className={cn(box, 'flex items-center justify-center font-bold text-white select-none', TEXT[size])}
      style={{ width: px, height: px, backgroundColor: getTeamColor(name) }}
      title={name}
      role="img"
      aria-label={name}
    >
      {getTeamInitials(name)}
    </div>
  )
}
