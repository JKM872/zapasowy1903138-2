// ============================================================================
// FilterBar – main filtering interface
// ============================================================================
'use client'

import { format } from 'date-fns'
import {
  Filter, X, CalendarIcon, Search, ArrowUpDown,
} from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Slider } from '@/components/ui/slider'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Popover, PopoverContent, PopoverTrigger,
} from '@/components/ui/popover'
import { Calendar } from '@/components/ui/calendar'
import { cn } from '@/lib/utils'
import { SPORTS, QUICK_FILTERS } from '@/lib/constants'
import { SportIcon } from '@/components/shared/SportIcon'
import { useFilterStore } from '@/store/filterStore'
import type { Sport } from '@/lib/types'

export function FilterBar() {
  const store = useFilterStore()

  return (
    <Card className="p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-muted-foreground" />
          <span className="font-semibold text-sm">Filters</span>
          {store.activeFilterCount > 0 && (
            <Badge variant="secondary" className="text-[10px]">{store.activeFilterCount}</Badge>
          )}
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 text-xs"
          onClick={store.resetFilters}
          disabled={store.activeFilterCount === 0}
        >
          <X className="h-3 w-3 mr-1" /> Clear
        </Button>
      </div>

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Search teams or competition…"
          className="pl-8 h-9 text-sm"
          value={store.search}
          onChange={(e) => store.setSearch(e.target.value)}
        />
      </div>

      {/* Row of main filters */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {/* Sport */}
        <div className="space-y-1.5">
          <Label className="text-xs">Sport</Label>
          <Select value={store.sport} onValueChange={(v) => store.setSport(v as Sport | 'all')}>
            <SelectTrigger className="h-9 text-sm">
              <SelectValue placeholder="All sports" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All sports</SelectItem>
              {SPORTS.map((s) => (
                <SelectItem key={s.id} value={s.id}>
                  <span className="flex items-center gap-2">
                    <SportIcon sport={s.id} colored className="text-[16px]" />
                    {s.name}
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Date */}
        <div className="space-y-1.5">
          <Label className="text-xs">Date</Label>
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outline" className="w-full h-9 justify-start text-sm font-normal">
                <CalendarIcon className="mr-2 h-3.5 w-3.5" />
                {store.date ? format(store.date, 'dd MMM yyyy') : 'Pick date'}
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-auto p-0" align="start">
              <Calendar
                mode="single"
                selected={store.date ?? undefined}
                onSelect={(d) => store.setDate(d ?? null)}
              />
            </PopoverContent>
          </Popover>
        </div>

        {/* Confidence */}
        <div className="space-y-1.5">
          <Label className="text-xs">Min confidence: {store.minConfidence}%</Label>
          <Slider
            value={[store.minConfidence]}
            onValueChange={([v]) => store.setMinConfidence(v)}
            min={0}
            max={100}
            step={5}
            className="pt-2"
          />
        </div>

        {/* Sort */}
        <div className="space-y-1.5">
          <Label className="text-xs">Sort by</Label>
          <div className="flex gap-1">
            <Select
              value={store.sortBy}
              onValueChange={(v) => store.setSortBy(v as 'time' | 'confidence' | 'sport')}
            >
              <SelectTrigger className="h-9 text-sm flex-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="time">Time</SelectItem>
                <SelectItem value="confidence">Confidence</SelectItem>
                <SelectItem value="sport">Sport</SelectItem>
              </SelectContent>
            </Select>
            <Button variant="outline" size="icon" className="h-9 w-9 shrink-0" onClick={store.toggleSortOrder}>
              <ArrowUpDown className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      </div>

      {/* Toggles */}
      <div className="flex flex-wrap gap-x-6 gap-y-2">
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <Switch checked={store.hasOdds} onCheckedChange={store.setHasOdds} className="scale-90" />
          Has Odds
        </label>
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <Switch checked={store.hasPredictions} onCheckedChange={store.setHasPredictions} className="scale-90" />
          Has Predictions
        </label>
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <Switch checked={store.hasSofascore} onCheckedChange={store.setHasSofascore} className="scale-90" />
          Has SofaScore
        </label>
      </div>

      {/* Quick presets */}
      <div className="flex flex-wrap gap-1.5 border-t pt-3">
        {QUICK_FILTERS.map((qf) => (
          <Badge
            key={qf.label}
            variant="outline"
            className="cursor-pointer text-xs hover:bg-primary hover:text-primary-foreground transition-colors"
            onClick={() => store.applyQuickFilter(qf.action as Parameters<typeof store.applyQuickFilter>[0])}
          >
            {qf.label}
          </Badge>
        ))}
      </div>
    </Card>
  )
}
