"use client";

import { useEffect, useState } from "react";
import { Check } from "lucide-react";

interface ToastProps {
  message: string;
  show: boolean;
  onClose: () => void;
}

export function Toast({ message, show, onClose }: ToastProps) {
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
        "fixed left-1/2 top-16 -translate-x-1/2 z-[10000]",
        "transition-[opacity,transform] duration-300 ease-out",
        show ? "opacity-100 translate-y-0" : "opacity-0 -translate-y-2",
      ].join(" ")}
      role="status"
      aria-live="polite"
    >
      <div className="flex items-center gap-2 bg-[#242628] border border-white/10 rounded-xl px-4 py-3 shadow-[0_14px_40px_rgba(0,0,0,0.45)]">
        <Check className="h-4 w-4 text-green-500 flex-shrink-0" />
        <p className="text-sm text-[#FCFCFC]">{message}</p>
      </div>
    </div>
  );
}

export function useToast() {
  const [show, setShow] = useState(false);
  const [message, setMessage] = useState("");

  const showToast = (msg: string) => {
    setMessage(msg);
    setShow(true);
  };

  const hideToast = () => {
    setShow(false);
  };

  return { show, message, showToast, hideToast };
}
