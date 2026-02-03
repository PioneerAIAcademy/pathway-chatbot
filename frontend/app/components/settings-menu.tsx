"use client";

import * as React from "react";
import { useTheme } from "next-themes";
import { HelpCircle, MessageSquare, Monitor, Moon, Settings, Sun } from "lucide-react";

import { Button } from "./ui/button";
import { GeneralFeedbackDrawer } from "./general-feedback-drawer";

export function SettingsMenu() {
  const [isOpen, setIsOpen] = React.useState(false);
  const [isRotating, setIsRotating] = React.useState(false);
  const [isFeedbackOpen, setIsFeedbackOpen] = React.useState(false);
  const { theme, setTheme } = useTheme();

  const hints =
    "https://missionaries.prod.byu-pathway.psdops.com/How-to-use-the-Missionary-Assistant";

  const handleToggle = () => {
    setIsRotating(true);
    setIsOpen((v) => !v);
    window.setTimeout(() => setIsRotating(false), 300);
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
          className="hover:bg-black/5 dark:hover:bg-white/10 p-0 h-9 w-9 rounded-full"
          title="Settings"
        >
          <Settings
            className={`h-5 w-5 text-[#646362] transition-transform duration-300 ${
              isRotating ? "rotate-90" : ""
            }`}
          />
        </Button>

        {isOpen && (
          <div
            className="absolute right-0 top-10 w-48 rounded-xl shadow-lg border border-black/10 dark:border-white/10 bg-[#FAF9F5] dark:bg-[#111213] p-2 z-[9999] pointer-events-auto animate-in fade-in slide-in-from-top-2 duration-200"
            onClick={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
          >
            {/* Feedback */}
            <button
              type="button"
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                openFeedback();
              }}
              className="w-full flex items-center gap-2 rounded-lg px-2.5 py-2 text-sm text-[#3D3D3A] dark:text-white hover:bg-black/5 dark:hover:bg-white/10 transition-colors"
            >
              <MessageSquare className="h-4 w-4 text-[#E18158]" />
              <span className="font-medium">Feedback</span>
            </button>

            <div className="my-2 h-px bg-black/10 dark:bg-white/10" />

            {/* Theme */}
            <div className="px-2.5 pb-2">
              <h3 className="text-[10px] font-semibold text-[#454540] dark:text-white/90 mb-1.5">
                Theme
              </h3>
              <div className="flex items-center gap-1">
                <button
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    handleThemeChange("light");
                  }}
                  className={`h-8 w-8 rounded-lg flex items-center justify-center hover:bg-black/5 dark:hover:bg-white/10 transition-colors ${
                    theme === "light" ? "bg-black/10 dark:bg-white/10" : ""
                  }`}
                  title="Light"
                >
                  <Sun className="h-4 w-4 text-[#454540] dark:text-white/80" />
                </button>
                <button
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    handleThemeChange("dark");
                  }}
                  className={`h-8 w-8 rounded-lg flex items-center justify-center hover:bg-black/5 dark:hover:bg-white/10 transition-colors ${
                    theme === "dark" ? "bg-black/10 dark:bg-white/10" : ""
                  }`}
                  title="Dark"
                >
                  <Moon className="h-4 w-4 text-[#454540] dark:text-white/80" />
                </button>
                <button
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    handleThemeChange("system");
                  }}
                  className={`h-8 w-8 rounded-lg flex items-center justify-center hover:bg-black/5 dark:hover:bg-white/10 transition-colors ${
                    theme === "system" ? "bg-black/10 dark:bg-white/10" : ""
                  }`}
                  title="System"
                >
                  <Monitor className="h-4 w-4 text-[#454540] dark:text-white/80" />
                </button>
              </div>
            </div>

            <div className="my-2 h-px bg-black/10 dark:bg-white/10" />

            {/* Help */}
            <a
              href={hints}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 rounded-lg px-2.5 py-2 text-sm text-[#3D3D3A] dark:text-white hover:bg-black/5 dark:hover:bg-white/10 transition-colors"
              onClick={(e) => {
                e.stopPropagation();
              }}
            >
              <HelpCircle className="h-4 w-4 text-[#646362] dark:text-white/70" />
              <span>Help</span>
            </a>
          </div>
        )}
      </div>

      <GeneralFeedbackDrawer isOpen={isFeedbackOpen} onClose={() => setIsFeedbackOpen(false)} />
    </>
  );
}

