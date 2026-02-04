"use client";

import { useEffect, useState } from "react";
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

  if (!mounted) return null;

  return (
    <div
      className={[
        "fixed left-0 right-0 z-[10000]",
        "top-4 sm:top-16 sm:left-1/2 sm:right-auto sm:-translate-x-1/2",
        "mx-4 sm:mx-0",
        "sm:w-auto sm:max-w-md",
        "transition-[opacity,transform] duration-300 ease-out",
        show ? "opacity-100 translate-y-0" : "opacity-0 -translate-y-2",
      ].join(" ")}
      role="status"
      aria-live="polite"
    >
      <div className="flex items-center gap-2 rounded-xl px-4 py-3 border shadow-[0_14px_40px_rgba(0,0,0,0.12)] bg-[#FFFEFA]/95 backdrop-blur-md border-black/10 text-[#3D3D3A] dark:bg-[#242628] dark:border-white/10 dark:text-[#FCFCFC] dark:shadow-[0_14px_40px_rgba(0,0,0,0.45)]">
        {type === "success" && <Check className="h-4 w-4 text-green-500 flex-shrink-0" />}
        {type === "error" && <X className="h-4 w-4 text-red-500 flex-shrink-0" />}
        <p className="text-sm">{message}</p>
      </div>
    </div>
  );
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
