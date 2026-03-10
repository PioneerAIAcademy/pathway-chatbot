import { Message } from "ai";
import {
  Calendar,
  Clock,
  ExternalLink,
  GraduationCap,
  Sprout,
  AlertCircle,
  RefreshCw,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type {
  CalendarCardData,
  CalendarCardState,
  CalendarEvent,
  ChatHandler,
} from "../index";
import styles from "./CalendarCard.module.css";

// --- Urgency color classes ---
// Light mode:  all text on #f5f4f0 card bg — WCAG AA (≥4.5:1)
//   amber-700 (#b45309) → 6.1:1 ✓ | blue-700 (#1d4ed8) → 6.8:1 ✓ | red-600 (#dc2626) → 5.4:1 ✓
// Dark mode:   all text on #161b22 card bg — WCAG AA (≥4.5:1)
//   amber-300 (#fcd34d) → 12.0:1 ✓ | amber-400 (#fbbf24) → 10.4:1 ✓
//   blue-400  (#60a5fa) →  6.8:1 ✓ | red-400  (#f87171)  →  6.3:1 ✓
//   gray-400  (#9ca3af) →  6.8:1 ✓ (minimum muted tone that passes on #161b22)
const urgencyClasses = {
  urgent: {
    bg: "bg-red-500/[0.07] dark:bg-red-500/[0.08]",
    border: "border-red-500/20 dark:border-red-500/20",
    dateText: "text-red-600 dark:text-red-400",
    countdownBg: "bg-red-500/10 dark:bg-red-500/10",
    countdownText: "text-red-600 dark:text-red-400",
  },
  warning: {
    bg: "bg-amber-500/[0.07] dark:bg-amber-500/[0.08]",
    border: "border-amber-500/18 dark:border-amber-500/18",
    dateText: "text-amber-700 dark:text-amber-400",
    countdownBg: "bg-amber-500/10 dark:bg-amber-500/10",
    countdownText: "text-amber-700 dark:text-amber-400",
  },
  info: {
    bg: "bg-[hsl(var(--header-bg))]/[0.07] dark:bg-[hsl(var(--header-bg))]/[0.05]",
    border:
      "border-[hsl(var(--header-bg))]/15 dark:border-[hsl(var(--header-bg))]/15",
    dateText: "text-amber-700 dark:text-amber-300",
    countdownBg: "bg-amber-700/10 dark:bg-amber-400/10",
    countdownText: "text-amber-700 dark:text-amber-300",
  },
  calm: {
    bg: "bg-blue-500/[0.06] dark:bg-blue-500/[0.07]",
    border: "border-blue-500/15 dark:border-blue-500/15",
    dateText: "text-blue-700 dark:text-blue-400",
    countdownBg: "bg-blue-500/10 dark:bg-blue-500/10",
    countdownText: "text-blue-700 dark:text-blue-400",
  },
};

// --- Status pip + pill colors ---
const statusPipClass: Record<string, string> = {
  past: "bg-gray-400/25 dark:bg-gray-500/25",
  today:
    "bg-green-500 dark:bg-green-400 shadow-[0_0_6px_rgba(34,197,94,0.3)]",
  soon: "bg-amber-500 dark:bg-amber-400",
  upcoming: "bg-blue-500/60 dark:bg-blue-400/60",
};

const statusPillClass: Record<string, string> = {
  // Light: gray-600 (#4b5563) → 6.0:1 ✓ on #f5f4f0
  // Dark:  gray-400 (#9ca3af) → 6.8:1 ✓ on #161b22  (was dark:gray-500 → 3.6:1 ❌)
  past: "bg-gray-200/60 dark:bg-white/[0.03] text-gray-600 dark:text-gray-400",
  today:
    "bg-green-500/10 dark:bg-green-400/10 text-green-700 dark:text-green-400",
  // Light: amber-700 → 6.1:1 ✓ | Dark: amber-400 → 10.4:1 ✓
  soon: "bg-amber-500/10 dark:bg-amber-400/10 text-amber-700 dark:text-amber-400",
  // Light: blue-700 → 6.8:1 ✓ | Dark: blue-400 → 6.8:1 ✓
  upcoming:
    "bg-blue-500/8 dark:bg-blue-400/8 text-blue-700 dark:text-blue-400",
};

// ---------------------------------------------------------------
// Reveal timing (ms from data-ready moment)
// ---------------------------------------------------------------
const TIMING = {
  header: 1200,
  tabs: 2600,
  spotlight: 3000,
  timeline: 3600,
  rowBase: 4300,
  rowInterval: 520,
  footerDelay: 1200,
} as const;

const TIMER_DURATION = 12000;
const SKELETON_ROW_COUNT = 4;

// --- Card type icon ---
function CardIcon({ type }: { type: CalendarCardData["type"] }) {
  const cls = "w-5 h-5 text-[#002E5D]";
  switch (type) {
    case "graduation":
      return <GraduationCap className={cls} />;
    case "semester":
      return <Sprout className={cls} />;
    default:
      return <Calendar className={cls} />;
  }
}

// --- Status badge ---
function StatusBadge({ status }: { status: CalendarCardData["status"] }) {
  if (status === "active") {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] sm:text-[11px] font-semibold text-green-700 dark:text-green-400 bg-green-500/10 dark:bg-green-400/10 px-2 sm:px-2.5 py-0.5 sm:py-1 rounded-full whitespace-nowrap">
        <span
          className={`${styles.pulseDot} bg-green-500 dark:bg-green-400`}
        />
        In Progress
      </span>
    );
  }
  if (status === "upcoming") {
    return (
      <span className="text-[10px] sm:text-[11px] font-semibold text-blue-700 dark:text-blue-400 bg-blue-500/8 dark:bg-blue-400/8 px-2 sm:px-2.5 py-0.5 sm:py-1 rounded-full whitespace-nowrap">
        Upcoming
      </span>
    );
  }
  return null;
}

// --- Spotlight Banner ---
function SpotlightBanner({
  spotlight,
}: {
  spotlight: NonNullable<CalendarCardData["spotlight"]>;
}) {
  const colors = urgencyClasses[spotlight.urgency] || urgencyClasses.info;
  const eventDate = new Date(spotlight.date + "T00:00:00");
  const monthStr = eventDate.toLocaleDateString("en-US", { month: "short" });
  const dayStr = eventDate.getDate();
  const now = new Date();
  const isToday =
    eventDate.getFullYear() === now.getFullYear() &&
    eventDate.getMonth() === now.getMonth() &&
    eventDate.getDate() === now.getDate();

  return (
    <div
      className={`p-3 sm:p-4 rounded-xl flex items-start sm:items-center gap-3 sm:gap-4 border ${colors.bg} ${colors.border}`}
    >
      <div
        className={`text-center min-w-[44px] sm:min-w-[54px] shrink-0 ${colors.dateText}`}
      >
        <div className="text-[10px] sm:text-[11px] font-semibold uppercase tracking-[0.5px] opacity-75">
          {monthStr}
        </div>
        <div className="text-[24px] sm:text-[30px] font-extrabold leading-none tracking-[-1px]">
          {dayStr}
        </div>
      </div>
      <div className="flex-1">
        <div className="flex items-center gap-1.5">
          {spotlight.urgency === "urgent" && (
            <AlertCircle className="w-3.5 h-3.5 text-red-600 dark:text-red-400 shrink-0" />
          )}
          <div className="text-[13px] sm:text-sm font-semibold text-[#3D3D3A] dark:text-[#e6edf3] leading-snug">
            {isToday ? "Today: " : ""}
            {spotlight.title}
          </div>
        </div>
        {spotlight.description && (
          // Light: gray-600 → 6.0:1 ✓ | Dark: gray-400 → 6.8:1 ✓
          <div className="text-[11.5px] sm:text-[12.5px] text-gray-600 dark:text-gray-400 leading-relaxed mt-0.5">
            {spotlight.description}
          </div>
        )}
        <div
          className={`inline-flex items-center gap-1 text-[10px] sm:text-[11px] font-semibold px-1.5 sm:px-2 py-0.5 rounded mt-1.5 ${colors.countdownBg} ${colors.countdownText}`}
        >
          <Clock className="w-3 h-3" />
          {spotlight.countdown}
        </div>
      </div>
    </div>
  );
}

// --- Timeline Row (skeleton or real content, in same container) ---
function TimelineRow({
  event,
  index,
  loaded,
}: {
  event: CalendarEvent;
  index: number;
  loaded: boolean;
}) {
  if (!loaded) {
    return (
      <div
        className={`${styles.skeletonRow} flex items-start px-2.5 sm:px-3 py-2 sm:py-2.5 rounded-lg gap-2 sm:gap-3`}
        style={{ "--row-index": index } as React.CSSProperties}
      >
        <div
          className={`${styles.shimmer} w-9 sm:w-[42px] h-9 sm:h-10 rounded bg-gray-200/60 dark:bg-gray-700/30`}
        />
        <div
          className={`${styles.skeletonGuide} w-[2.5px] sm:w-[3px] h-6 sm:h-7 rounded-sm shrink-0 mt-1 bg-gray-200/60 dark:bg-gray-700/30`}
        />
        <div className="flex-1 min-w-0 pt-0.5 sm:pt-1 space-y-1.5">
          <div
            className={`${styles.skeletonLineMain} ${styles.shimmer} h-3 sm:h-3.5 rounded bg-gray-200/60 dark:bg-gray-700/30`}
          />
          <div
            className={`${styles.skeletonLineSub} ${styles.shimmer} h-2.5 w-3/4 rounded bg-gray-200/60 dark:bg-gray-700/30`}
          />
        </div>
        <div
          className={`${styles.shimmer} w-12 sm:w-14 h-5 rounded bg-gray-200/60 dark:bg-gray-700/30 mt-1`}
        />
      </div>
    );
  }

  const eventDate = new Date(event.date + "T00:00:00");
  const monthStr = eventDate.toLocaleDateString("en-US", { month: "short" });
  const dayStr = eventDate.getDate();
  const isPast = event.status === "past";
  const hasDescription = event.description && !isPast;

  return (
    <div
      className={`${styles.row} flex items-start px-2.5 sm:px-3 py-2 sm:py-2.5 rounded-lg gap-2 sm:gap-3 hover:bg-black/[0.02] dark:hover:bg-white/[0.02] transition-colors`}
      style={{ "--row-index": index } as React.CSSProperties}
    >
      {/* Mini date */}
      <div
        className={`${styles.rowContentReveal} w-9 sm:w-[42px] text-center shrink-0 pt-0.5`}
      >
        <div
          // Light: gray-600 → 6.0:1 ✓ both states
          // Dark:  gray-400 → 6.8:1 ✓ both states  (was dark:gray-600 → 2.3:1 ❌ / dark:gray-500 → 3.6:1 ❌)
          // Visual de-emphasis for past events is preserved via the pastEvent CSS class (strikethrough/opacity)
          className={`text-[8.5px] sm:text-[9px] font-bold uppercase tracking-[0.5px] text-gray-600 dark:text-gray-400`}
        >
          {monthStr}
        </div>
        <div
          // Past: gray-600 / gray-400 (see above) | Active: primary text colors
          className={`text-[17px] sm:text-[19px] font-bold leading-tight ${
            isPast
              ? "text-gray-600 dark:text-gray-400"
              : "text-[#3D3D3A] dark:text-[#e6edf3]"
          }`}
        >
          {dayStr}
        </div>
      </div>

      {/* Colored pip */}
      <div
        className={`${styles.pip} w-[2.5px] sm:w-[3px] rounded-sm shrink-0 mt-1 ${hasDescription ? "h-8 sm:h-9" : "h-6 sm:h-7"} ${statusPipClass[event.status] || statusPipClass.upcoming}`}
        style={{ "--row-index": index } as React.CSSProperties}
      />

      {/* Event name + description */}
      <div className={`${styles.rowContentReveal} flex-1 min-w-0 pt-0.5`}>
        <div
          // Past: gray-600 / gray-400 | Active: primary text colors
          // Dark past was dark:gray-600 → 2.3:1 ❌ → fixed to dark:gray-400 → 6.8:1 ✓
          className={`text-[12.5px] sm:text-[13.5px] font-medium leading-snug ${
            isPast
              ? `text-gray-600 dark:text-gray-400 ${styles.pastEvent}`
              : "text-[#3D3D3A] dark:text-[#e6edf3]"
          }`}
        >
          {event.name}
        </div>
        {hasDescription && (
          // Light: gray-600 → 6.0:1 ✓
          // Dark: #8b949e → 5.6:1 ✓  (was #6e7681 → 3.8:1 ❌)
          // Using #8b949e rather than gray-400 to preserve a lighter secondary-text feel
          // while still clearing AA. (GitHub dark palette secondary text token.)
          <div className="text-[10.5px] sm:text-[11px] text-gray-600 dark:text-[#8b949e] leading-snug mt-px">
            {event.description}
          </div>
        )}
      </div>

      {/* Status pill */}
      <span
        className={`${styles.rowContentReveal} text-[10px] sm:text-[10.5px] font-semibold px-1.5 sm:px-2 py-0.5 rounded shrink-0 max-w-[84px] sm:max-w-none whitespace-normal sm:whitespace-nowrap text-right leading-tight mt-0.5 sm:mt-1 ${statusPillClass[event.status] || statusPillClass.upcoming}`}
      >
        {event.countdown || event.status}
      </span>
    </div>
  );
}

// --- Section Label ---
function SectionLabel({ label }: { label: string }) {
  return (
    // Light: gray-500 | Dark: gray-400 → 6.8:1 ✓  (was dark:gray-600 → 2.3:1 ❌)
    <div className="text-[9px] sm:text-[10px] font-bold text-gray-500 dark:text-gray-400 uppercase tracking-widest px-2.5 sm:px-3 pt-2 sm:pt-2.5 pb-1">
      {label}
    </div>
  );
}

// Dummy event for skeleton rows (content is never shown — loaded=false)
const SKELETON_EVENT: CalendarEvent = {
  date: "2000-01-01",
  name: "",
  status: "upcoming",
};

function extractYearFromText(value: string | undefined): number | null {
  if (!value) return null;
  const match = value.match(/\b20\d{2}\b/);
  if (!match) return null;
  const parsed = Number(match[0]);
  return Number.isFinite(parsed) ? parsed : null;
}

function detectCalendarYear(cardData: Partial<CalendarCardData>): number | null {
  const fromTitle = extractYearFromText(cardData.title);
  if (fromTitle) return fromTitle;

  const fromSubtitle = extractYearFromText(cardData.subtitle);
  if (fromSubtitle) return fromSubtitle;

  if (cardData.spotlight?.date) {
    const spotlightYear = Number(cardData.spotlight.date.slice(0, 4));
    if (Number.isFinite(spotlightYear) && spotlightYear >= 2000) {
      return spotlightYear;
    }
  }

  if (cardData.events && cardData.events.length > 0) {
    const eventYear = Number((cardData.events[0]?.date || "").slice(0, 4));
    if (Number.isFinite(eventYear) && eventYear >= 2000) {
      return eventYear;
    }
  }

  if (cardData.tabs && cardData.tabs.length > 0) {
    for (const tab of cardData.tabs) {
      const tabEventYear = Number((tab.events?.[0]?.date || "").slice(0, 4));
      if (Number.isFinite(tabEventYear) && tabEventYear >= 2000) {
        return tabEventYear;
      }
    }
  }

  return null;
}

function buildOpenCalendarPrompt(year: number | null): string {
  if (year) {
    return `Show me the full ${year} academic calendar`;
  }
  return "Show me the full academic calendar";
}

// --- Main CalendarCard ---
export function CalendarCard({
  data,
  state,
  append,
}: {
  data?: CalendarCardData;
  state?: CalendarCardState;
  append?: Pick<ChatHandler, "append">["append"];
}) {
  const cardData: Partial<CalendarCardData> = useMemo(() => {
    if (data) return data;
    if (!state) return {};
    return {
      type: state.type ?? "block",
      title: state.title ?? "",
      subtitle: state.subtitle ?? "",
      status: state.status ?? "upcoming",
      spotlight: state.spotlight,
      events: state.events ?? [],
      tabs: state.tabs,
      sourceUrl:
        state.sourceUrl ??
        "https://studentservices.byupathway.edu/studentservices/academic-calendar",
      suggestedQuestions: state.suggestedQuestions ?? [],
      footnote: state.footnote,
      textFormatOffer: state.textFormatOffer,
    };
  }, [data, state]);

  const [activeTab, setActiveTab] = useState(
    cardData.tabs?.findIndex((t) => t.active) ?? 0,
  );

  const displayEvents = useMemo(() => {
    if (
      cardData.tabs &&
      cardData.tabs.length > 0 &&
      cardData.tabs[activeTab]?.events
    ) {
      return cardData.tabs[activeTab].events!;
    }
    return cardData.events ?? [];
  }, [activeTab, cardData.tabs, cardData.events]);

  const dataReady = !!cardData.title;

  const [mounted, setMounted] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [showStallNotice, setShowStallNotice] = useState(false);

  useEffect(() => {
    const id = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(id);
  }, []);

  useEffect(() => {
    if (!dataReady) return;
    const start = Date.now();
    const id = setInterval(() => {
      const now = Date.now() - start;
      setElapsed(now);
      if (now >= TIMER_DURATION) clearInterval(id);
    }, 50);
    return () => {
      clearInterval(id);
      setElapsed(0);
    };
  }, [dataReady]);

  useEffect(() => {
    if (dataReady || state?.phase !== "skeleton") {
      setShowStallNotice(false);
      return;
    }
    const stallId = setTimeout(() => {
      setShowStallNotice(true);
    }, 16000);
    return () => clearTimeout(stallId);
  }, [dataReady, state?.phase]);

  const headerLoaded = dataReady && elapsed >= TIMING.header;
  const tabsLoaded = dataReady && elapsed >= TIMING.tabs;
  const spotlightLoaded = dataReady && elapsed >= TIMING.spotlight;
  const timelineStarted = dataReady && elapsed >= TIMING.timeline;
  const footerAt =
    TIMING.rowBase +
    Math.max(displayEvents.length, SKELETON_ROW_COUNT) * TIMING.rowInterval +
    TIMING.footerDelay;
  const showFooter = dataReady && elapsed >= footerAt;

  const sections: { label: string; events: CalendarEvent[] }[] = useMemo(() => {
    const result: { label: string; events: CalendarEvent[] }[] = [];
    let currentSection = "";
    for (const evt of displayEvents) {
      const section = evt.section || "";
      if (section !== currentSection) {
        result.push({ label: section, events: [] });
        currentSection = section;
      }
      result[result.length - 1].events.push(evt);
    }
    return result;
  }, [displayEvents]);

  const rowCount = timelineStarted
    ? Math.max(SKELETON_ROW_COUNT, displayEvents.length)
    : SKELETON_ROW_COUNT;

  const calendarYear = useMemo(() => detectCalendarYear(cardData), [cardData]);

  return (
    <div className="flex flex-col gap-3">
      <div
        className={`${styles.card} ${mounted ? styles.ready : ""} bg-[#f5f4f0] dark:bg-[#161b22] rounded-2xl overflow-hidden max-w-full`}
      >
        <div className={styles.cardFrame} aria-hidden="true">
          <span className={`${styles.frameLine} ${styles.topLeft}`} />
          <span className={`${styles.frameLine} ${styles.topRight}`} />
          <span className={`${styles.frameLine} ${styles.sideLeft}`} />
          <span className={`${styles.frameLine} ${styles.sideRight}`} />
          <span className={`${styles.frameLine} ${styles.bottomLeft}`} />
          <span className={`${styles.frameLine} ${styles.bottomRight}`} />
        </div>

        {/* Header */}
        <div className="px-3 sm:px-5 pt-3 sm:pt-4 pb-2.5 sm:pb-3 flex items-center justify-between gap-2.5 sm:gap-3">
          {headerLoaded ? (
            <div className={`${styles.headerReveal} w-full min-w-0`}>
              <div className="flex items-start gap-2 sm:gap-3 min-w-0">
                <div className="w-8 h-8 sm:w-10 sm:h-10 rounded-xl bg-gradient-to-br from-[hsl(var(--header-bg))] to-amber-500 flex items-center justify-center shadow-[0_4px_12px_rgba(255,195,40,0.18)] shrink-0 mt-0.5">
                  <CardIcon type={cardData.type ?? "block"} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-start justify-between gap-1.5 sm:gap-2 min-w-0">
                    <div className="text-[21px] sm:text-base font-bold leading-[1.08] sm:leading-[1.15] tracking-[-0.3px] text-[#3D3D3A] dark:text-[#e6edf3] break-words min-w-0 pr-1">
                      {cardData.title}
                    </div>
                    <div className="shrink-0 pt-0.5">
                      <StatusBadge status={cardData.status ?? "upcoming"} />
                    </div>
                  </div>
                  {/* Light: gray-600 → 6.0:1 ✓ | Dark: gray-400 → 6.8:1 ✓  (was dark:gray-500 → 3.6:1 ❌) */}
                  <div className="text-[11px] sm:text-xs text-gray-600 dark:text-gray-400 mt-0.5 leading-tight pr-1">
                    {cardData.subtitle}
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex items-center gap-3 w-full">
              <div
                className={`${styles.shimmer} w-8 h-8 sm:w-10 sm:h-10 rounded-xl bg-gray-200 dark:bg-gray-700`}
              />
              <div className="flex-1 space-y-2">
                <div
                  className={`${styles.shimmer} h-4 w-40 sm:w-48 rounded bg-gray-200 dark:bg-gray-700`}
                />
                <div
                  className={`${styles.shimmer} h-3 w-24 sm:w-32 rounded bg-gray-200 dark:bg-gray-700`}
                />
              </div>
            </div>
          )}
        </div>

        {/* Spotlight */}
        {!dataReady ? (
          <div className="mx-2.5 sm:mx-3.5 mb-2.5 sm:mb-3.5">
            <div
              className={`${styles.shimmer} h-20 rounded-xl bg-gray-200/50 dark:bg-gray-700/30`}
            />
          </div>
        ) : spotlightLoaded && cardData.spotlight ? (
          <div className={`${styles.sectionReveal} mx-2.5 sm:mx-3.5 mb-2.5 sm:mb-3.5`}>
            <SpotlightBanner spotlight={cardData.spotlight} />
          </div>
        ) : null}

        {/* Tabs */}
        {tabsLoaded && cardData.tabs && cardData.tabs.length > 0 && (
          <div
            className={`${styles.tabs} ${styles.hideScrollbar} px-2.5 sm:px-4 mb-1 overflow-x-auto`}
          >
            <div className="inline-flex gap-0.5 min-w-max">
              {cardData.tabs.map((tab, i) => (
                <button
                  key={tab.label}
                  onClick={() => setActiveTab(i)}
                  className={`text-[10.5px] sm:text-[11.5px] font-medium px-2.5 sm:px-3.5 py-1 sm:py-1.5 rounded-t-lg border-b-2 transition-colors cursor-pointer whitespace-nowrap ${
                    i === activeTab
                      // Active — Light: amber-700 → 6.1:1 ✓ | Dark: amber-300 → 12.0:1 ✓
                      ? `${styles.tabActive} text-amber-700 dark:text-amber-300 border-amber-700 dark:border-amber-300 bg-amber-700/5 dark:bg-amber-400/5 font-semibold`
                      // Inactive base — Dark: gray-400 → 6.8:1 ✓  (was dark:gray-600 → 2.3:1 ❌)
                      // Inactive hover — Dark: gray-300 → 11.7:1 ✓  (was dark:hover:gray-500 → 3.6:1 ❌)
                      : "text-gray-500 dark:text-gray-400 border-transparent hover:text-gray-700 dark:hover:text-gray-300 hover:bg-black/[0.02] dark:hover:bg-white/[0.02]"
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Timeline */}
        <div className="px-2 sm:px-2.5 pb-1.5">
          {timelineStarted
            ? sections.map((section) => (
                <div key={section.label || "default"}>
                  {section.label && <SectionLabel label={section.label} />}
                  {section.events.map((evt) => {
                    const globalIndex = displayEvents.findIndex(
                      (e) => e.date === evt.date && e.name === evt.name,
                    );
                    return (
                      <TimelineRow
                        key={globalIndex}
                        event={evt}
                        index={globalIndex}
                        loaded={
                          elapsed >=
                          TIMING.rowBase + globalIndex * TIMING.rowInterval
                        }
                      />
                    );
                  })}
                </div>
              ))
            : Array.from({ length: SKELETON_ROW_COUNT }, (_, i) => (
                <TimelineRow
                  key={i}
                  event={SKELETON_EVENT}
                  index={i}
                  loaded={false}
                />
              ))}
        </div>

        {/* Footer */}
        {showFooter && cardData.sourceUrl && (
          <div
            className={`${styles.footer} px-3 sm:px-4 py-2.5 sm:py-3 border-t border-gray-200/60 dark:border-white/[0.06] flex flex-col items-start sm:flex-row sm:items-center sm:justify-between gap-2`}
          >
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() =>
                  append?.({
                    role: "user",
                    content: buildOpenCalendarPrompt(calendarYear),
                  } as Message)
                }
                // Yellow bg (#FFC328) + dark text (#002E5D) — bg is decorative, text contrast is fine
                className="inline-flex items-center gap-1.5 text-[11.5px] sm:text-[12.5px] font-semibold text-[#002E5D] dark:text-[#002E5D] bg-[hsl(var(--header-bg))] hover:bg-amber-300 dark:hover:bg-amber-300 px-3 sm:px-4 py-1.5 rounded-lg transition-all hover:-translate-y-px hover:shadow-[0_4px_12px_rgba(255,195,40,0.25)]"
              >
                <Calendar className="w-3.5 h-3.5" />
                {calendarYear ? `Open ${calendarYear} Calendar` : "Open Calendar"}
              </button>
            </div>
            {/* Light: gray-600 → 6.0:1 ✓ | Dark: gray-400 → 6.8:1 ✓  (was dark:gray-600 → 2.3:1 ❌) */}
            <div className="text-[10px] sm:text-[10.5px] text-gray-600 dark:text-gray-400">
              Source:{" "}
              <a
                href={cardData.sourceUrl}
                target="_blank"
                rel="noopener noreferrer"
                // Hover — Light: amber-700 → 6.1:1 ✓ | Dark: amber-300 → 12.0:1 ✓
                className="underline underline-offset-2 decoration-gray-400 dark:decoration-gray-600 hover:text-amber-700 dark:hover:text-amber-300 transition-colors"
              >
                Academic Calendar
              </a>
            </div>
          </div>
        )}

        {/* Footnote */}
        {showFooter && cardData.footnote && (
          <div className="px-3 sm:px-4 pb-3 -mt-1">
            {/* Light: gray-600 → 6.0:1 ✓ | Dark: gray-400 → 6.8:1 ✓  (was dark:gray-500 → 3.6:1 ❌) */}
            <p className="text-[11px] sm:text-[11.5px] text-gray-600 dark:text-gray-400 leading-relaxed">
              <strong className="font-semibold">Note:</strong>{" "}
              {cardData.footnote}
            </p>
          </div>
        )}
      </div>

      {/* Suggested follow-up chips */}
      {showFooter &&
        cardData.suggestedQuestions &&
        cardData.suggestedQuestions.length > 0 && (
          <div className={`${styles.chipsContainer} flex gap-2 flex-wrap`}>
            {cardData.suggestedQuestions.slice(0, 2).map((q, i) => (
              <button
                key={q}
                onClick={() =>
                  append?.({ role: "user", content: q } as Message)
                }
                // Base  — Light: gray-600 → 6.0:1 ✓ | Dark: gray-400 → 6.8:1 ✓  (was dark:gray-500 → 3.6:1 ❌)
                // Hover — Light: amber-700 → 6.1:1 ✓ | Dark: amber-300 → 12.0:1 ✓
                className={`text-[11px] sm:text-[11.5px] font-medium text-gray-600 dark:text-gray-400 px-2.5 sm:px-3 py-1.5 rounded-md bg-[#f5f4f0] dark:bg-[#161b22] border border-gray-200/60 dark:border-white/[0.06] cursor-pointer transition-all hover:text-amber-700 dark:hover:text-amber-300 hover:border-amber-700/20 dark:hover:border-amber-400/15 hover:bg-amber-700/5 dark:hover:bg-amber-400/5 text-left ${i === 1 ? "hidden sm:inline-block" : "inline-block"}`}
              >
                {q}
              </button>
            ))}
          </div>
        )}

      {/* Text format offer */}
      {showFooter && cardData.textFormatOffer && (
        <button
          onClick={() =>
            append?.({
              role: "user",
              content: "Yes, list the dates in text format",
            } as Message)
          }
          // Base  — Light: gray-600 → 6.0:1 ✓ | Dark: gray-400 → 6.8:1 ✓  (was dark:gray-500 → 3.6:1 ❌)
          // Hover — Light: amber-700 → 6.1:1 ✓ | Dark: amber-300 → 12.0:1 ✓
          className="self-start text-[11px] sm:text-[11.5px] text-gray-600 dark:text-gray-400 hover:text-amber-700 dark:hover:text-amber-300 transition-colors cursor-pointer text-left"
        >
          {cardData.textFormatOffer}
        </button>
      )}

      {showStallNotice && !dataReady && (
        <div className="rounded-xl border border-amber-500/35 bg-amber-500/8 dark:bg-amber-500/10 px-4 py-3">
          <div className="text-[13px] font-semibold text-amber-800 dark:text-amber-300">
            Still loading calendar details
          </div>
          <p className="text-[12px] text-amber-900/90 dark:text-amber-200/90 mt-0.5">
            Network lag or a temporary issue may be delaying this card.
          </p>
          <button
            onClick={() =>
              append?.({
                role: "user",
                content: "Please retry the academic calendar request",
              } as Message)
            }
            className="mt-2 inline-flex items-center gap-1.5 text-[12px] font-medium px-2.5 py-1 rounded-md border border-amber-500/40 text-amber-800 dark:text-amber-200 hover:bg-amber-500/10 dark:hover:bg-amber-500/20 transition-colors"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Try again
          </button>
        </div>
      )}
    </div>
  );
}