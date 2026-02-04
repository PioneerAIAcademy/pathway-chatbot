"use client";

import * as React from "react";
import { useTheme } from "next-themes";
import { HelpCircle, MessageSquare, Monitor, Moon, Settings, Sun } from "lucide-react";

import { Button } from "./ui/button";
import { GeneralFeedbackDrawer } from "./general-feedback-drawer";

export function SettingsMenu() {
  const [isOpen, setIsOpen] = React.useState(false);
  const [isFeedbackOpen, setIsFeedbackOpen] = React.useState(false);
  const { theme, setTheme } = useTheme();

  const hints =
    "https://missionaries.prod.byu-pathway.psdops.com/How-to-use-the-Missionary-Assistant";

  const handleToggle = () => {
    setIsOpen((v) => !v);
  };

  const handleThemeChange = (newTheme: string) => {
    setTheme(newTheme);
    setIsOpen(false);
  };

  const openFeedback = () => {
    setIsOpen(false);
    setIsFeedbackOpen(true);
  };

  // Close dropdown when clicking outside.
  React.useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as HTMLElement;
      if (isOpen && !target.closest(".settings-menu-container")) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }

    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isOpen]);

  return (
    <>
      <div className="settings-menu-container relative flex items-center">
        <Button
          variant="ghost"
          size="icon"
          onClick={handleToggle}
          aria-haspopup="menu"
          aria-expanded={isOpen}
          className={[
            "p-0 h-9 w-9 rounded-full",
            "hover:bg-black/5 dark:hover:bg-white/10",
            "transition-colors",
            isOpen ? "bg-black/5 dark:bg-white/10" : "",
          ].join(" ")}
          title="Settings"
        >
          <Settings
            className={[
              "h-5 w-5 text-[#646362]",
              "transition-transform duration-200 ease-out",
              isOpen ? "rotate-90" : "rotate-0",
            ].join(" ")}
          />
        </Button>

        {isOpen && (
          <div
            className={[
              "absolute right-0 top-11",
              "w-[248px]",
              "rounded-2xl",
              "border border-black/10 dark:border-white/10",
              "ring-1 ring-black/5 dark:ring-white/5",
              "bg-[#FFFEFA]/95 dark:bg-[#0E0F10]/95 backdrop-blur-md",
              "shadow-[0_18px_48px_rgba(0,0,0,0.16)] dark:shadow-[0_18px_60px_rgba(0,0,0,0.62)]",
              "p-2.5",
              "z-[9999] pointer-events-auto origin-top-right",
              "animate-in fade-in zoom-in-95 duration-150",
            ].join(" ")}
            onClick={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
          >
            {/* Theme */}
            <div className="px-1 pb-2.5">
              <h3 className="text-[10px] font-semibold tracking-wide text-[#454540] dark:text-white/80 mb-1.5">
                Theme
              </h3>
              <div className="flex items-center gap-1 rounded-xl border border-black/10 dark:border-white/10 bg-black/[0.035] dark:bg-white/5 p-1">
                <button
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    handleThemeChange("light");
                  }}
                  className={[
                    "h-9 w-9 rounded-lg flex items-center justify-center",
                    "transition-colors",
                    "text-[#646362] dark:text-white/70",
                    "hover:bg-black/5 dark:hover:bg-white/10",
                    theme === "light"
                      ? "bg-[#FFC328]/45 text-[#3D3D3A] dark:bg-white/10 dark:text-white shadow-[0_1px_0_rgba(0,0,0,0.06)]"
                      : "",
                  ].join(" ")}
                  title="Light"
                >
                  <Sun className="h-4 w-4" />
                </button>
                <button
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    handleThemeChange("dark");
                  }}
                  className={[
                    "h-9 w-9 rounded-lg flex items-center justify-center",
                    "transition-colors",
                    "text-[#646362] dark:text-white/70",
                    "hover:bg-black/5 dark:hover:bg-white/10",
                    theme === "dark"
                      ? "bg-[#FFC328]/45 text-[#3D3D3A] dark:bg-white/10 dark:text-white shadow-[0_1px_0_rgba(0,0,0,0.06)]"
                      : "",
                  ].join(" ")}
                  title="Dark"
                >
                  <Moon className="h-4 w-4" />
                </button>
                <button
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    handleThemeChange("system");
                  }}
                  className={[
                    "h-9 w-9 rounded-lg flex items-center justify-center",
                    "transition-colors",
                    "text-[#646362] dark:text-white/70",
                    "hover:bg-black/5 dark:hover:bg-white/10",
                    theme === "system"
                      ? "bg-[#FFC328]/45 text-[#3D3D3A] dark:bg-white/10 dark:text-white shadow-[0_1px_0_rgba(0,0,0,0.06)]"
                      : "",
                  ].join(" ")}
                  title="System"
                >
                  <Monitor className="h-4 w-4" />
                </button>
              </div>
            </div>

            <div className="my-2 h-px bg-black/10 dark:bg-white/10" />

            {/* Help */}
            <a
              href={hints}
              target="_blank"
              rel="noopener noreferrer"
              className="group flex items-center gap-3 rounded-xl px-2 py-2 text-sm font-medium text-[#3D3D3A] dark:text-white hover:bg-black/5 dark:hover:bg-white/10 transition-colors"
              onClick={(e) => {
                e.stopPropagation();
              }}
            >
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-black/5 dark:bg-white/10 group-hover:bg-[#FFC328]/25 dark:group-hover:bg-[#FFC328]/15 transition-colors">
                <HelpCircle className="h-4 w-4 text-[#646362] dark:text-white/70 group-hover:text-[#3D3D3A] dark:group-hover:text-white transition-colors" />
              </span>
              <span>Help</span>
            </a>

            <div className="my-2 h-px bg-black/10 dark:bg-white/10" />

            {/* Send feedback */}
            <button
              type="button"
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                openFeedback();
              }}
              className="group w-full flex items-center gap-3 rounded-xl px-2 py-2 text-sm font-medium text-[#3D3D3A] dark:text-white hover:bg-black/5 dark:hover:bg-white/10 transition-colors"
            >
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-black/5 dark:bg-white/10 group-hover:bg-[#FFC328]/25 dark:group-hover:bg-[#FFC328]/15 transition-colors">
                <MessageSquare className="h-4 w-4 text-[#E18158]" />
              </span>
              <span>Send feedback</span>
            </button>
          </div>
        )}
      </div>

      <GeneralFeedbackDrawer isOpen={isFeedbackOpen} onClose={() => setIsFeedbackOpen(false)} />
    </>
  );
}
