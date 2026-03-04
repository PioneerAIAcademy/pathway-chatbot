import { Message } from "ai";
import {
  Calendar,
  Clock,
  ExternalLink,
  GraduationCap,
  Sprout,
  AlertCircle,
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
const urgencyClasses = {
  urgent: {
    bg: "bg-red-500/[0.07] dark:bg-red-500/[0.08]",
    border: "border-red-500/20 dark:border-red-500/20",
    dateText: "text-red-500 dark:text-red-400",
    countdownBg: "bg-red-500/10 dark:bg-red-500/10",
    countdownText: "text-red-500 dark:text-red-400",
  },
  warning: {
    bg: "bg-amber-500/[0.07] dark:bg-amber-500/[0.08]",
    border: "border-amber-500/18 dark:border-amber-500/18",
    dateText: "text-amber-600 dark:text-amber-400",
    countdownBg: "bg-amber-500/10 dark:bg-amber-500/10",
    countdownText: "text-amber-600 dark:text-amber-400",
  },
  info: {
    bg: "bg-[hsl(var(--header-bg))]/[0.07] dark:bg-[hsl(var(--header-bg))]/[0.05]",
    border:
      "border-[hsl(var(--header-bg))]/15 dark:border-[hsl(var(--header-bg))]/15",
    dateText: "text-[hsl(var(--header-bg))] dark:text-amber-300",
    countdownBg: "bg-[hsl(var(--header-bg))]/10 dark:bg-amber-400/10",
    countdownText: "text-[hsl(var(--header-bg))] dark:text-amber-300",
  },
  calm: {
    bg: "bg-blue-500/[0.06] dark:bg-blue-500/[0.07]",
    border: "border-blue-500/15 dark:border-blue-500/15",
    dateText: "text-blue-500 dark:text-blue-400",
    countdownBg: "bg-blue-500/10 dark:bg-blue-500/10",
    countdownText: "text-blue-500 dark:text-blue-400",
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
  past: "bg-gray-200/60 dark:bg-white/[0.03] text-gray-500 dark:text-gray-500",
  today:
    "bg-green-500/10 dark:bg-green-400/10 text-green-600 dark:text-green-400",
  soon: "bg-amber-500/10 dark:bg-amber-400/10 text-amber-600 dark:text-amber-400",
  upcoming:
    "bg-blue-500/8 dark:bg-blue-400/8 text-blue-500 dark:text-blue-400",
};

// ---------------------------------------------------------------
// Reveal timing (ms from data-ready moment)
// ---------------------------------------------------------------
const TIMING = {
  header: 200,
  tabs: 500,
  spotlight: 550,
  timeline: 800,
  rowBase: 1000,
  rowInterval: 180,
  footerDelay: 500,
} as const;

const TIMER_DURATION = 5000;
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
      <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-green-600 dark:text-green-400 bg-green-500/10 dark:bg-green-400/10 px-2.5 py-1 rounded-full whitespace-nowrap">
        <span
          className={`${styles.pulseDot} bg-green-500 dark:bg-green-400`}
        />
        In Progress
      </span>
    );
  }
  if (status === "upcoming") {
    return (
      <span className="text-[11px] font-semibold text-blue-500 dark:text-blue-400 bg-blue-500/8 dark:bg-blue-400/8 px-2.5 py-1 rounded-full whitespace-nowrap">
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

  return (
    <div
      className={`p-4 rounded-xl flex items-center gap-4 border ${colors.bg} ${colors.border}`}
    >
      <div
        className={`text-center min-w-[54px] shrink-0 ${colors.dateText}`}
      >
        <div className="text-[11px] font-semibold uppercase tracking-wide opacity-75">
          {monthStr}
        </div>
        <div className="text-[30px] font-extrabold leading-none -tracking-wider">
          {dayStr}
        </div>
      </div>
      <div className="flex-1">
        <div className="flex items-center gap-1.5">
          {spotlight.urgency === "urgent" && (
            <AlertCircle className="w-3.5 h-3.5 text-red-500 dark:text-red-400 shrink-0" />
          )}
          <div className="text-sm font-semibold text-[#3D3D3A] dark:text-[#e6edf3] leading-snug">
            {spotlight.urgency === "urgent" ? "Today: " : ""}
            {spotlight.title}
          </div>
        </div>
        {spotlight.description && (
          <div className="text-[12.5px] text-gray-500 dark:text-gray-400 leading-relaxed mt-0.5">
            {spotlight.description}
          </div>
        )}
        <div
          className={`inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded mt-1.5 ${colors.countdownBg} ${colors.countdownText}`}
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
    // Skeleton content — same layout, shimmer placeholders
    return (
      <div
        className={`${styles.skeletonRow} flex items-start px-3 py-2.5 rounded-lg gap-3`}
        style={{ "--row-index": index } as React.CSSProperties}
      >
        <div
          className={`${styles.shimmer} w-[42px] h-10 rounded bg-gray-200/60 dark:bg-gray-700/30`}
        />
        <div className="w-[3px] h-7 rounded-sm shrink-0 mt-1 bg-gray-200/60 dark:bg-gray-700/30" />
        <div className="flex-1 min-w-0 pt-1 space-y-1.5">
          <div
            className={`${styles.shimmer} h-3.5 rounded bg-gray-200/60 dark:bg-gray-700/30`}
          />
          <div
            className={`${styles.shimmer} h-2.5 w-3/4 rounded bg-gray-200/60 dark:bg-gray-700/30`}
          />
        </div>
        <div
          className={`${styles.shimmer} w-14 h-5 rounded bg-gray-200/60 dark:bg-gray-700/30 mt-1`}
        />
      </div>
    );
  }

  // Real content
  const eventDate = new Date(event.date + "T00:00:00");
  const monthStr = eventDate.toLocaleDateString("en-US", { month: "short" });
  const dayStr = eventDate.getDate();
  const isPast = event.status === "past";
  const hasDescription = event.description && !isPast;

  return (
    <div
      className={`${styles.row} flex items-start px-3 py-2.5 rounded-lg gap-3 hover:bg-black/[0.02] dark:hover:bg-white/[0.02] transition-colors`}
      style={{ "--row-index": index } as React.CSSProperties}
    >
      {/* Mini date */}
      <div
        className={`${styles.rowContentReveal} w-[42px] text-center shrink-0 pt-0.5`}
      >
        <div
          className={`text-[9px] font-bold uppercase tracking-wide ${isPast ? "text-gray-400 dark:text-gray-600" : "text-gray-500 dark:text-gray-500"}`}
        >
          {monthStr}
        </div>
        <div
          className={`text-[19px] font-bold leading-tight ${isPast ? "text-gray-400 dark:text-gray-600" : "text-[#3D3D3A] dark:text-[#e6edf3]"}`}
        >
          {dayStr}
        </div>
      </div>

      {/* Colored pip */}
      <div
        className={`${styles.pip} w-[3px] rounded-sm shrink-0 mt-1 ${hasDescription ? "h-9" : "h-7"} ${statusPipClass[event.status] || statusPipClass.upcoming}`}
        style={{ "--row-index": index } as React.CSSProperties}
      />

      {/* Event name + description */}
      <div className={`${styles.rowContentReveal} flex-1 min-w-0 pt-0.5`}>
        <div
          className={`text-[13.5px] font-medium leading-snug ${
            isPast
              ? `text-gray-400 dark:text-gray-600 ${styles.pastEvent}`
              : "text-[#3D3D3A] dark:text-[#e6edf3]"
          }`}
        >
          {event.name}
        </div>
        {hasDescription && (
          <div className="text-[11px] text-gray-500 dark:text-[#6e7681] leading-snug mt-px">
            {event.description}
          </div>
        )}
      </div>

      {/* Status pill */}
      <span
        className={`${styles.rowContentReveal} text-[10.5px] font-semibold px-2 py-0.5 rounded shrink-0 whitespace-nowrap mt-1 ${statusPillClass[event.status] || statusPillClass.upcoming}`}
      >
        {event.countdown || event.status}
      </span>
    </div>
  );
}

// --- Section Label ---
function SectionLabel({ label }: { label: string }) {
  return (
    <div className="text-[10px] font-bold text-gray-400 dark:text-gray-600 uppercase tracking-widest px-3 pt-2.5 pb-1">
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
  // Merge state and/or data into a unified view
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

  // For functional tab switching: use tab-specific events if available
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

  // Data is "ready" once we have at least header info
  const dataReady = !!cardData.title;

  // ---------------------------------------------------------------
  // Frame drawing starts on mount (card is always the same DOM node).
  // Content reveal timer starts when data arrives.
  // ---------------------------------------------------------------
  const [mounted, setMounted] = useState(false);
  const [elapsed, setElapsed] = useState(0);

  // Card frame animation — starts immediately on mount
  useEffect(() => {
    const id = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(id);
  }, []);

  // Elapsed timer — starts when data arrives
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

  // Section visibility based on elapsed time
  const headerLoaded = dataReady && elapsed >= TIMING.header;
  const tabsLoaded = dataReady && elapsed >= TIMING.tabs;
  const spotlightLoaded = dataReady && elapsed >= TIMING.spotlight;
  const timelineStarted = dataReady && elapsed >= TIMING.timeline;
  const footerAt =
    TIMING.rowBase +
    Math.max(displayEvents.length, SKELETON_ROW_COUNT) * TIMING.rowInterval +
    TIMING.footerDelay;
  const showFooter = dataReady && elapsed >= footerAt;

  // Group events by section (only used once timeline is loaded)
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

  // How many rows to render: keep stable to avoid layout jumps
  const rowCount = timelineStarted
    ? Math.max(SKELETON_ROW_COUNT, displayEvents.length)
    : SKELETON_ROW_COUNT;

  return (
    <div className="flex flex-col gap-3">
      {/* The card — never unmounts, content transitions in-place */}
      <div
        className={`${styles.card} ${mounted ? styles.ready : ""} bg-[#f5f4f0] dark:bg-[#161b22] border border-gray-200/60 dark:border-white/[0.06] rounded-2xl overflow-hidden`}
      >
        {/* Card frame — 6 lines draw the border from center outward */}
        <div className={styles.cardFrame} aria-hidden="true">
          <span className={`${styles.frameLine} ${styles.topLeft}`} />
          <span className={`${styles.frameLine} ${styles.topRight}`} />
          <span className={`${styles.frameLine} ${styles.sideLeft}`} />
          <span className={`${styles.frameLine} ${styles.sideRight}`} />
          <span className={`${styles.frameLine} ${styles.bottomLeft}`} />
          <span className={`${styles.frameLine} ${styles.bottomRight}`} />
        </div>

        {/* Header — container always present, content swaps in-place */}
        <div className="px-5 pt-4 pb-3 flex items-center justify-between gap-3">
          {headerLoaded ? (
            <div
              className={`${styles.sectionReveal} flex items-center justify-between gap-3 w-full`}
            >
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[hsl(var(--header-bg))] to-amber-500 flex items-center justify-center shadow-[0_4px_12px_rgba(255,195,40,0.18)] shrink-0">
                  <CardIcon type={cardData.type ?? "block"} />
                </div>
                <div>
                  <div className="text-base font-bold tracking-[-0.3px] text-[#3D3D3A] dark:text-[#e6edf3]">
                    {cardData.title}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-500 mt-px">
                    {cardData.subtitle}
                  </div>
                </div>
              </div>
              <StatusBadge status={cardData.status ?? "upcoming"} />
            </div>
          ) : (
            <div className="flex items-center gap-3 w-full">
              <div
                className={`${styles.shimmer} w-10 h-10 rounded-xl bg-gray-200 dark:bg-gray-700`}
              />
              <div className="flex-1 space-y-2">
                <div
                  className={`${styles.shimmer} h-4 w-48 rounded bg-gray-200 dark:bg-gray-700`}
                />
                <div
                  className={`${styles.shimmer} h-3 w-32 rounded bg-gray-200 dark:bg-gray-700`}
                />
              </div>
            </div>
          )}
        </div>

        {/* Spotlight — show shimmer while loading, real content when ready, nothing if no spotlight */}
        {!dataReady ? (
          <div className="mx-3.5 mb-3.5">
            <div
              className={`${styles.shimmer} h-20 rounded-xl bg-gray-200/50 dark:bg-gray-700/30`}
            />
          </div>
        ) : spotlightLoaded && cardData.spotlight ? (
          <div className={`${styles.sectionReveal} mx-3.5 mb-3.5`}>
            <SpotlightBanner spotlight={cardData.spotlight} />
          </div>
        ) : null}

        {/* Tabs (semester view) — mounts when ready */}
        {tabsLoaded && cardData.tabs && cardData.tabs.length > 0 && (
          <div className={`${styles.tabs} flex gap-0.5 px-4 mb-1`}>
            {cardData.tabs.map((tab, i) => (
              <button
                key={tab.label}
                onClick={() => setActiveTab(i)}
                className={`text-[11.5px] font-medium px-3.5 py-1.5 rounded-t-lg border-b-2 transition-colors cursor-pointer ${
                  i === activeTab
                    ? `${styles.tabActive} text-[hsl(var(--header-bg))] dark:text-amber-300 border-[hsl(var(--header-bg))] dark:border-amber-300 bg-[hsl(var(--header-bg))]/5 dark:bg-amber-400/5 font-semibold`
                    : "text-gray-400 dark:text-gray-600 border-transparent hover:text-gray-500 dark:hover:text-gray-500 hover:bg-black/[0.02] dark:hover:bg-white/[0.02]"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        )}

        {/* Timeline — always present, rows fill content in-place */}
        <div className="px-2.5 pb-1.5">
          {timelineStarted
            ? // Real rows — with section labels and per-row loading
              sections.map((section) => (
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
            : // Skeleton rows — stable layout, visible immediately
              Array.from({ length: SKELETON_ROW_COUNT }, (_, i) => (
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
            className={`${styles.footer} px-4 py-3 border-t border-gray-200/60 dark:border-white/[0.06] flex items-center justify-between flex-wrap gap-2`}
          >
            <div className="flex gap-2">
              <a
                href={cardData.sourceUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-[12.5px] font-semibold text-[#002E5D] dark:text-[#002E5D] bg-[hsl(var(--header-bg))] hover:bg-amber-300 dark:hover:bg-amber-300 px-4 py-1.5 rounded-lg transition-all hover:-translate-y-px hover:shadow-[0_4px_12px_rgba(255,195,40,0.25)]"
              >
                <Calendar className="w-3.5 h-3.5" />
                Full Calendar
                <ExternalLink className="w-3 h-3" />
              </a>
            </div>
            <div className="text-[10.5px] text-gray-400 dark:text-gray-600">
              Source:{" "}
              <a
                href={cardData.sourceUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="underline underline-offset-2 decoration-gray-300 dark:decoration-gray-700 hover:text-[hsl(var(--header-bg))] dark:hover:text-amber-300 transition-colors"
              >
                Academic Calendar
              </a>
            </div>
          </div>
        )}

        {/* Footnote */}
        {showFooter && cardData.footnote && (
          <div className="px-4 pb-3 -mt-1">
            <p className="text-[11.5px] text-gray-400 dark:text-gray-500 leading-relaxed">
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
            {cardData.suggestedQuestions.map((q) => (
              <button
                key={q}
                onClick={() =>
                  append?.({ role: "user", content: q } as Message)
                }
                className="text-[11.5px] font-medium text-gray-500 dark:text-gray-500 px-3 py-1.5 rounded-md bg-[#f5f4f0] dark:bg-[#161b22] border border-gray-200/60 dark:border-white/[0.06] cursor-pointer transition-all hover:text-[hsl(var(--header-bg))] dark:hover:text-amber-300 hover:border-[hsl(var(--header-bg))]/15 dark:hover:border-amber-400/15 hover:bg-[hsl(var(--header-bg))]/5 dark:hover:bg-amber-400/5"
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
          className="text-[11.5px] text-gray-400 dark:text-gray-500 hover:text-[hsl(var(--header-bg))] dark:hover:text-amber-300 transition-colors cursor-pointer text-left"
        >
          {cardData.textFormatOffer}
        </button>
      )}
    </div>
  );
}
