"use client";

import * as Sentry from "@sentry/nextjs";
import { useChat } from "ai/react";
import { useState, useEffect, useRef } from "react";
import { AlertTriangle, X } from "lucide-react";
import DisclaimerMessage from "./disclaimer-message";
import Greeting from "./greeting";
import { ChatInput, ChatMessages } from "./ui/chat";
import { useClientConfig } from "./ui/chat/hooks/use-config";
import { getSessionId, getDeviceId, getTimezone } from "../utils/session";

export default function ChatSection() {
  const { backend } = useClientConfig();
  const [requestData, setRequestData] = useState<any>();
  const [isAcmChecked, setIsAcmChecked] = useState(false);
  const [hasStartedChat, setHasStartedChat] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const [deviceId, setDeviceId] = useState<string>("");

  // Load device fingerprint on mount (async)
  useEffect(() => {
    getDeviceId().then(setDeviceId);
  }, []);
  
  const {
    messages,
    input,
    isLoading,
    handleSubmit,
    handleInputChange,
    reload,
    stop,
    append,
    setInput,
    setMessages,
  } = useChat({
    body: { data: requestData },
    api: `${backend}/api/v1/chat`,
    headers: {
      "Content-Type": "application/json",
      "X-Session-ID": getSessionId(),
      "X-Device-ID": deviceId,
      "X-Timezone": getTimezone(),
      "X-API-Key": process.env.NEXT_PUBLIC_API_KEY ?? "",
    },
    onError: (error: unknown) => {
      if (!(error instanceof Error)) throw error;
      // Always show a friendly message — never expose raw errors to the user
      const friendlyMessage = "Something went wrong. Please try again.";
      // Extract raw detail for Sentry diagnostics only
      let rawDetail = error.message;
      try {
        const parsed = JSON.parse(error.message);
        rawDetail = parsed.detail ?? error.message;
      } catch {
        // error.message is not JSON — use as-is for Sentry
      }
      Sentry.captureException(error, {
        extra: { rawDetail },
      });
      setChatError(friendlyMessage);
    },
  });

  const customHandleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    const role = isAcmChecked ? "ACM" : "missionary";
    const data = {
      question: input,
      role: role,
    };
    setRequestData(data);
    
    // Mark chat as started on first message
    if (!hasStartedChat) {
      setHasStartedChat(true);
    }
    
    handleSubmit(e, {
      body: {
        data: data,
      },
    });
  };

  // Check if there are any messages
  const hasMessages = messages.length > 0;

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    if (scrollContainerRef.current) {
      const prefersReducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ?? false;
      scrollContainerRef.current.scrollTo({
        top: scrollContainerRef.current.scrollHeight,
        behavior: prefersReducedMotion ? "auto" : "smooth",
      });
    }
  }, [messages.length, isLoading]);

  return (
    <div className="w-full h-full flex flex-col relative overflow-hidden">
      {/* Empty state - centered */}
      {!hasStartedChat && !hasMessages && (
        <div className="flex-1 flex items-center justify-center px-4">
          <div className="w-full max-w-[672px] md:max-w-[720px] lg:max-w-[840px] xl:max-w-[960px] 2xl:max-w-[1120px] flex flex-col items-center gap-8">
            <Greeting />
            <DisclaimerMessage />
          </div>
        </div>
      )}

      {/* Chat messages - takes remaining space */}
      {(hasStartedChat || hasMessages) && (
        <div
          ref={scrollContainerRef}
          className="flex-1 overflow-y-auto overflow-x-hidden scroll-smooth px-4 md:px-8 lg:px-16 xl:px-24 2xl:px-32 pt-8 pb-24"
          style={{ scrollBehavior: 'smooth' }}
        >
          <div className="max-w-[640px] md:max-w-[720px] lg:max-w-[840px] xl:max-w-[960px] 2xl:max-w-[1120px] mx-auto">
            <ChatMessages
              messages={messages}
              isLoading={isLoading}
              reload={reload}
              stop={stop}
              append={append}
              setMessages={setMessages}
            />
          </div>
        </div>
      )}

      {/* Compact centered error banner */}
      {chatError && (
        <div className="flex justify-center mb-2 px-4">
          <div
            className={[
              "relative overflow-hidden",
              "flex items-center gap-2.5 rounded-xl px-4 py-2.5 border",
              "bg-white/95 backdrop-blur-md border-red-300 text-[#3D3D3A]",
              "shadow-[0_12px_36px_rgba(0,0,0,0.12)]",
              "ring-1 ring-red-200/60",
              "dark:bg-[#242628] dark:border-red-800/60 dark:text-[#FCFCFC]",
              "dark:shadow-[0_14px_40px_rgba(0,0,0,0.45)]",
              "dark:ring-red-900/30",
              "before:content-[''] before:absolute before:left-0 before:top-0 before:h-full before:w-1.5 before:bg-red-500",
              "animate-error-slide-in",
            ].join(" ")}
          >
            <AlertTriangle className="h-4 w-4 text-red-500 dark:text-red-400 flex-shrink-0" />
            <p className="text-xs sm:text-sm font-medium">{chatError}</p>
            <button
              onClick={() => setChatError(null)}
              className="text-gray-400 hover:text-gray-600 dark:text-gray-500 dark:hover:text-gray-300 transition-colors flex-shrink-0"
              aria-label="Dismiss error"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* Input area - positioned based on chat state */}
      <div
        className={`w-full px-4 sm:px-6 md:px-8 lg:px-16 xl:px-24 2xl:px-32 pb-2 transition-all duration-500 ease-in-out ${
          !hasStartedChat && !hasMessages ? 'static' : 'sticky bottom-0'
        }`}
      >
        <div className="max-w-[672px] md:max-w-[720px] lg:max-w-[840px] xl:max-w-[960px] 2xl:max-w-[1120px] mx-auto space-y-2">
          {/* Input with ACM Toggle inside */}
          <ChatInput
            input={input}
            handleSubmit={customHandleSubmit}
            handleInputChange={handleInputChange}
            isLoading={isLoading}
            messages={messages}
            append={append}
            setInput={setInput}
            stop={stop}
            requestParams={{ params: requestData }}
            setRequestData={setRequestData}
            isAcmMode={isAcmChecked}
            isAcmChecked={isAcmChecked}
            setIsAcmChecked={setIsAcmChecked}
          />
          
          {/* Disclaimer under input - only show before first message */}
          {!hasStartedChat && !hasMessages && (
            <div className="px-2">
              <p className="text-[10px] sm:text-xs leading-[14px] sm:leading-[16px] text-red-500 dark:text-red-400">
                <span className="font-bold">IMPORTANT:</span> <span className="font-medium opacity-80">This website is intended for missionaries assigned to BYU-Pathway only — not for student use. Please direct students to the Companion app in their portal. We ask that you do not share or promote this site on social media. Thank you for respecting this guideline.</span>
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
