// ============================================================================
// CompactFilters – FlashScore-style top filter bar
// ============================================================================
'use client'

import {
  Search,
  SlidersHorizontal,
  Sparkles,
  Zap,
  Target,
  ArrowUpDown,
  X,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Sheet, SheetContent, SheetTrigger, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'
import { useFilterStore } from '@/store/filterStore'
import { FilterBar } from './FilterBar'

const QUICK_CHIPS = [
  {
    id: 'ai-picks',
    label: 'Typy modelu',
    icon: Sparkles,
    activeColor: 'bg-amber-500/15 text-amber-700 dark:text-amber-400 border-amber-300/50',
    filter: { geminiRecommendation: 'HIGH' as const, hasPredictions: true },
    check: (f: ReturnType<typeof useFilterStore.getState>) =>
      f.geminiRecommendation === 'HIGH',
  },
  {
    id: 'value-bets',
    label: 'Wartość',
    icon: Zap,
    activeColor: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border-emerald-300/50',
    filter: { hasOdds: true, hasPredictions: true },
    check: (f: ReturnType<typeof useFilterStore.getState>) =>
      f.hasOdds && f.hasPredictions,
  },
  {
    id: 'high-conf',
    label: 'Wysoka pewność',
    icon: Target,
    activeColor: 'bg-blue-500/15 text-blue-700 dark:text-blue-400 border-blue-300/50',
    filter: { minConfidence: 75, hasPredictions: true },
    check: (f: ReturnType<typeof useFilterStore.getState>) =>
      f.minConfidence >= 75,
  },
]

const SORT_OPTIONS = [
  { label: 'Godzina', value: 'time' as const },
  { label: 'Pewność', value: 'confidence' as const },
  { label: 'Dyscyplina', value: 'sport' as const },
]

export function CompactFilters() {
  const filters = useFilterStore()

  const toggleChip = (chip: typeof QUICK_CHIPS[number]) => {
    const isActive = chip.check(filters)
    if (isActive) {
      // Reset only the filters this chip controls
      filters.resetFilters()
    } else {
      filters.applyQuickFilter(chip.filter)
    }
  }

  return (
    <div className="flex items-center gap-2 overflow-x-auto py-1">
      {/* Search */}
      <div className="relative shrink-0 w-[180px] sm:w-[220px]">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
        <Input
          placeholder="Szukaj drużyn, lig..."
          value={filters.search}
          onChange={(e) => filters.setSearch(e.target.value)}
          className="h-8 pl-8 pr-8 text-xs"
        />
        {filters.search && (
          <button
            onClick={() => filters.setSearch('')}
            className="absolute right-2 top-1/2 -translate-y-1/2"
          >
            <X className="h-3.5 w-3.5 text-muted-foreground hover:text-foreground" />
          </button>
        )}
      </div>

      {/* Divider */}
      <div className="h-5 w-px bg-border shrink-0" />

      {/* Quick filter chips */}
      {QUICK_CHIPS.map((chip) => {
        const isActive = chip.check(filters)
        const Icon = chip.icon
        return (
          <Button
            key={chip.id}
            variant="outline"
            size="sm"
            onClick={() => toggleChip(chip)}
            className={cn(
              'h-7 gap-1 text-xs shrink-0 rounded-full',
              isActive && chip.activeColor,
            )}
          >
            <Icon className="h-3 w-3" />
            {chip.label}
          </Button>
        )
      })}

      {/* Spacer */}
      <div className="flex-1 min-w-0" />

      {/* Sort dropdown */}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="sm" className="h-7 gap-1 text-xs shrink-0">
            <ArrowUpDown className="h-3 w-3" />
            <span className="hidden sm:inline">
              {SORT_OPTIONS.find(o => o.value === filters.sortBy)?.label ?? 'Sortuj'}
            </span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {SORT_OPTIONS.map((opt) => (
            <DropdownMenuItem
              key={opt.value}
              onClick={() => filters.setSortBy(opt.value)}
              className={cn(filters.sortBy === opt.value && 'font-bold')}
            >
              {opt.label}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>

      {/* More filters (opens sheet with full FilterBar) */}
      <Sheet>
        <SheetTrigger asChild>
          <Button variant="ghost" size="sm" className="h-7 gap-1 text-xs shrink-0 relative">
            <SlidersHorizontal className="h-3 w-3" />
            <span className="hidden sm:inline">Filtry</span>
            {filters.activeFilterCount > 0 && (
              <Badge className="absolute -top-1 -right-1 h-4 w-4 p-0 flex items-center justify-center text-[9px] bg-primary text-primary-foreground">
                {filters.activeFilterCount}
              </Badge>
            )}
          </Button>
        </SheetTrigger>
        <SheetContent side="right" className="w-[320px] sm:w-[380px] overflow-y-auto">
          <SheetHeader>
            <SheetTitle>Filtry</SheetTitle>
          </SheetHeader>
          <div className="mt-4">
            <FilterBar />
          </div>
        </SheetContent>
      </Sheet>

      {/* Reset filters */}
      {filters.activeFilterCount > 0 && (
        <Button
          variant="ghost"
          size="sm"
          onClick={filters.resetFilters}
          className="h-7 gap-1 text-xs text-muted-foreground shrink-0"
        >
          <X className="h-3 w-3" />
          Wyczyść
        </Button>
      )}
    </div>
  )
}
