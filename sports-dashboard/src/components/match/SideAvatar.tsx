// ============================================================================
// SideAvatar – round logo / player photo for one side of a match.
// Wraps TeamLogo for team sports; for individual sports (tennis, table tennis)
// renders a player avatar circle (photo when the API sends one, else initials).
// ============================================================================
'use client'
import { useState } from 'react'
import { cn } from '@/lib/utils'
import { getTeamInitials, getTeamColor } from '@/lib/team-logos'
import { TeamLogo, MediaCredit } from './TeamLogo'
import type { Match, MediaInfo, Sport } from '@/lib/types'

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
  const media = side === 'home' ? match.homeMedia : match.awayMedia

  if (!isIndividualSport(match.sport)) {
    return (
      <TeamLogo
        name={name}
        size={size}
        media={media}
        badgeUrl={photo || logo}
        className={cn('ring-1 ring-border', className)}
      />
    )
  }
  return (
    <PlayerAvatar name={name} url={media?.url || photo || logo} media={media} size={size} className={className} />
  )
}

function PlayerAvatar({
  name, url, media, size, className,
}: { name: string; url?: string; media?: MediaInfo | null; size: Size; className?: string }) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null)
  const px = PX[size]
  const box = cn(
    'relative shrink-0 overflow-hidden rounded-full ring-1 ring-border',
    className,
  )
  if (url && failedUrl !== url) {
    return (
      <div className="relative shrink-0" style={{ width: px, height: px }}>
        <div className={cn(box, 'bg-muted')} style={{ width: px, height: px }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={url}
            alt={name}
            width={px}
            height={px}
            loading="lazy"
            referrerPolicy="no-referrer"
            className="h-full w-full object-cover object-top"
            onError={() => setFailedUrl(url)}
          />
        </div>
        <MediaCredit media={media?.url === url ? media : null} large={size === 'lg' || size === 'xl'} />
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
