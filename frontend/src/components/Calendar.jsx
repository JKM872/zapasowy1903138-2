import { useState } from 'react';
import { ChevronLeft, ChevronRight, Calendar as CalendarIcon, Check, Flame } from 'lucide-react';

/**
 * Calendar Component - Widok kalendarza meczów
 * Wyświetla mecze w formie kalendarza miesięcznego z kolorowym oznaczeniem wyników
 */
const Calendar = ({ matches = [], onDateSelect, selectedDate }) => {
    const [currentMonth, setCurrentMonth] = useState(new Date());

    // Pomocnicze funkcje
    const getDaysInMonth = (date) => {
        const year = date.getFullYear();
        const month = date.getMonth();
        return new Date(year, month + 1, 0).getDate();
    };

    const getFirstDayOfMonth = (date) => {
        const year = date.getFullYear();
        const month = date.getMonth();
        return new Date(year, month, 1).getDay();
    };

    const formatDate = (date) => {
        return date.toISOString().split('T')[0];
    };

    // Grupuj mecze według daty
    const matchesByDate = matches.reduce((acc, match) => {
        const date = match.date || formatDate(new Date());
        if (!acc[date]) acc[date] = [];
        acc[date].push(match);
        return acc;
    }, {});

    // Oblicz statystyki dla dnia
    const getDayStats = (dateStr) => {
        const dayMatches = matchesByDate[dateStr] || [];
        if (dayMatches.length === 0) return null;

        const qualifying = dayMatches.filter(m => m.qualifies).length;
        const withFormAdvantage = dayMatches.filter(m => m.formAdvantage).length;

        return {
            total: dayMatches.length,
            qualifying,
            withFormAdvantage,
            hasGoodPicks: qualifying > 0 && qualifying >= dayMatches.length * 0.5
        };
    };

    // Generuj dni miesiąca
    const generateCalendarDays = () => {
        const daysInMonth = getDaysInMonth(currentMonth);
        const firstDay = getFirstDayOfMonth(currentMonth);
        const days = [];

        // Puste dni na początku
        for (let i = 0; i < firstDay; i++) {
            days.push({ empty: true, key: `empty-${i}` });
        }

        // Dni miesiąca
        for (let day = 1; day <= daysInMonth; day++) {
            const date = new Date(currentMonth.getFullYear(), currentMonth.getMonth(), day);
            const dateStr = formatDate(date);
            const stats = getDayStats(dateStr);
            const isToday = formatDate(new Date()) === dateStr;
            const isSelected = selectedDate === dateStr;

            days.push({
                day,
                date: dateStr,
                stats,
                isToday,
                isSelected,
                key: dateStr
            });
        }

        return days;
    };

    const days = generateCalendarDays();
    const weekDays = ['Nd', 'Pn', 'Wt', 'Śr', 'Cz', 'Pt', 'Sb'];

    const prevMonth = () => {
        setCurrentMonth(new Date(currentMonth.getFullYear(), currentMonth.getMonth() - 1, 1));
    };

    const nextMonth = () => {
        setCurrentMonth(new Date(currentMonth.getFullYear(), currentMonth.getMonth() + 1, 1));
    };

    const monthNames = [
        'Styczeń', 'Luty', 'Marzec', 'Kwiecień', 'Maj', 'Czerwiec',
        'Lipiec', 'Sierpień', 'Wrzesień', 'Październik', 'Listopad', 'Grudzień'
    ];

    return (
        <div className="calendar-container glass-card p-4">
            {/* Header */}
            <div className="calendar-header flex items-center justify-between mb-4">
                <button
                    onClick={prevMonth}
                    className="calendar-nav-btn p-2 rounded-lg hover:bg-white/10 transition-colors"
                >
                    <ChevronLeft size={20} />
                </button>

                <div className="flex items-center gap-2">
                    <CalendarIcon size={20} className="text-blue-400" />
                    <h3 className="text-lg font-semibold">
                        {monthNames[currentMonth.getMonth()]} {currentMonth.getFullYear()}
                    </h3>
                </div>

                <button
                    onClick={nextMonth}
                    className="calendar-nav-btn p-2 rounded-lg hover:bg-white/10 transition-colors"
                >
                    <ChevronRight size={20} />
                </button>
            </div>

            {/* Legenda */}
            <div className="calendar-legend flex gap-4 mb-4 text-xs">
                <div className="flex items-center gap-1">
                    <span className="w-3 h-3 rounded-full bg-green-500/50"></span>
                    <span className="text-gray-400">Dobre typy</span>
                </div>
                <div className="flex items-center gap-1">
                    <span className="w-3 h-3 rounded-full bg-yellow-500/50"></span>
                    <span className="text-gray-400">Mecze</span>
                </div>
                <div className="flex items-center gap-1">
                    <span className="w-3 h-3 rounded-full bg-blue-500"></span>
                    <span className="text-gray-400">Dziś</span>
                </div>
            </div>

            {/* Dni tygodnia */}
            <div className="calendar-weekdays grid grid-cols-7 gap-1 mb-2">
                {weekDays.map(day => (
                    <div key={day} className="text-center text-xs text-gray-500 font-medium py-1">
                        {day}
                    </div>
                ))}
            </div>

            {/* Dni miesiąca */}
            <div className="calendar-days grid grid-cols-7 gap-1">
                {days.map((dayData) => {
                    if (dayData.empty) {
                        return <div key={dayData.key} className="calendar-day-empty h-12"></div>;
                    }

                    const { day, date, stats, isToday, isSelected } = dayData;

                    let bgClass = 'bg-white/5';
                    if (stats?.hasGoodPicks) {
                        bgClass = 'bg-green-500/20 border-green-500/30';
                    } else if (stats?.total > 0) {
                        bgClass = 'bg-yellow-500/10 border-yellow-500/20';
                    }
                    if (isToday) {
                        bgClass = 'bg-blue-500/30 border-blue-500/50';
                    }
                    if (isSelected) {
                        bgClass = 'bg-accent/30 border-accent ring-2 ring-accent/50';
                    }

                    return (
                        <button
                            key={date}
                            onClick={() => onDateSelect?.(date)}
                            className={`
                calendar-day h-12 rounded-lg border border-white/10
                flex flex-col items-center justify-center
                hover:bg-white/10 transition-all cursor-pointer
                ${bgClass}
              `}
                        >
                            <span className={`text-sm ${isToday ? 'font-bold text-blue-400' : ''}`}>
                                {day}
                            </span>
                            {stats && (
                                <span className="text-xs text-gray-400">
                                    {stats.qualifying}/{stats.total}
                                </span>
                            )}
                        </button>
                    );
                })}
            </div>

            {/* Footer - podsumowanie wybranego dnia */}
            {selectedDate && matchesByDate[selectedDate] && (
                <div className="calendar-footer mt-4 pt-4 border-t border-white/10">
                    <h4 className="text-sm font-medium mb-2">
                        {selectedDate} - {matchesByDate[selectedDate].length} mecz(ów)
                    </h4>
                    <div className="flex gap-4 text-xs text-gray-400">
                        <span className="flex items-center gap-1">
                            <Check size={12} className="text-green-500" />
                            Kwalifikujących: {matchesByDate[selectedDate].filter(m => m.qualifies).length}
                        </span>
                        <span className="flex items-center gap-1">
                            <Flame size={12} className="text-orange-500" />
                            Z przewagą formy: {matchesByDate[selectedDate].filter(m => m.formAdvantage).length}
                        </span>
                    </div>
                </div>
            )}
        </div>
    );
};

export default Calendar;
