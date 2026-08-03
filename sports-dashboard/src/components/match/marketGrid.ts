// ============================================================================
// Shared grid geometry for the event board
// ============================================================================
import { getSportConfig, MARKET_COLUMNS_2WAY, MARKET_COLUMNS_3WAY } from '@/lib/constants'

/**
 * The league header and every row underneath must use the exact same column
 * template, otherwise the odds buttons drift out from under their 1-X-2 labels.
 * Both class strings are written out in full so Tailwind can see them.
 */
export const MARKET_GRID_3WAY =
  'grid grid-cols-[46px_minmax(0,1fr)] lg:grid-cols-[46px_minmax(0,1fr)_repeat(3,54px)_58px]'

export const MARKET_GRID_2WAY =
  'grid grid-cols-[46px_minmax(0,1fr)] lg:grid-cols-[46px_minmax(0,1fr)_repeat(2,54px)_58px]'

export interface MarketLayout {
  /** Grid classes to apply to the header and each row. */
  gridClass: string
  /** Outcome keys, in column order. */
  columns: readonly string[]
}

/** Column layout for a sport: three-way where a draw is possible, else two-way. */
export function marketLayout(sport: string | null | undefined): MarketLayout {
  return getSportConfig(sport).hasDraw
    ? { gridClass: MARKET_GRID_3WAY, columns: MARKET_COLUMNS_3WAY }
    : { gridClass: MARKET_GRID_2WAY, columns: MARKET_COLUMNS_2WAY }
}
