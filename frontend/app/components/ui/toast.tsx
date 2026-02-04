"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Check, X } from "lucide-react";

export type ToastType = "info" | "success" | "error";

interface ToastProps {
  message: string;
  show: boolean;
  type?: ToastType;
  onClose: () => void;
}

export function Toast({ message, show, type = "info", onClose }: ToastProps) {
  const [mounted, setMounted] = useState(show);
  const [portalRoot, setPortalRoot] = useState<HTMLElement | null>(null);
  
  const accentClass =
    type === "success"
      ? "before:bg-green-500"
      : type === "error"
        ? "before:bg-red-500"
        : "before:bg-[#FFC328]";

  useEffect(() => {
    setPortalRoot(document.body);
  }, []);

  useEffect(() => {
    if (show) {
      const timer = setTimeout(() => {
        onClose();
      }, 3000);
      return () => clearTimeout(timer);
    }
  }, [show, onClose]);

  useEffect(() => {
    if (show) {
      setMounted(true);
      return;
    }

    // Allow exit transition to play before unmounting.
    const timer = setTimeout(() => setMounted(false), 260);
    return () => clearTimeout(timer);
  }, [show]);

  if (!mounted || !portalRoot) return null;

  const toastContent = (
    <div
      className={[
        "fixed left-1/2 -translate-x-1/2 z-[10000]",
        "top-4 sm:top-16",
        "w-auto max-w-[280px] sm:max-w-sm",
        "mx-4",
        "transition-[opacity,transform] duration-300 ease-out",
        show ? "opacity-100 translate-y-0" : "opacity-0 -translate-y-2",
      ].join(" ")}
      role="status"
      aria-live="polite"
    >
      <div
        className={[
          "relative overflow-hidden",
          "flex items-center gap-2 rounded-xl px-4 py-3 border",
          "bg-white/95 backdrop-blur-md border-black/20 text-[#3D3D3A]",
          "shadow-[0_18px_48px_rgba(0,0,0,0.18)]",
          "ring-1 ring-black/5",
          "dark:bg-[#242628] dark:border-white/10 dark:text-[#FCFCFC]",
          "dark:shadow-[0_14px_40px_rgba(0,0,0,0.45)]",
          accentClass,
          "before:content-[''] before:absolute before:left-0 before:top-0 before:h-full before:w-1.5",
        ].join(" ")}
      >
        {type === "success" && <Check className="h-4 w-4 text-green-500 flex-shrink-0" />}
        {type === "error" && <X className="h-4 w-4 text-red-500 flex-shrink-0" />}
        <p className="text-xs sm:text-sm font-medium whitespace-nowrap">{message}</p>
      </div>
    </div>
  );

  return createPortal(toastContent, portalRoot);
}

export function useToast() {
  const [show, setShow] = useState(false);
  const [message, setMessage] = useState("");
  const [type, setType] = useState<ToastType>("info");

  const showToast = (msg: string, toastType: ToastType = "info") => {
    setMessage(msg);
    setType(toastType);
    setShow(true);
  };

  const hideToast = () => {
    setShow(false);
  };

  return { show, message, type, showToast, hideToast };
}
