"use client";

import * as Sentry from "@sentry/nextjs";
import { useChat } from "ai/react";
import { useState, useEffect, useRef } from "react";
import DisclaimerMessage from "./disclaimer-message";
import Greeting from "./greeting";
import { ChatInput, ChatMessages } from "./ui/chat";
import { useClientConfig } from "./ui/chat/hooks/use-config";
import { getSessionId, getDeviceId } from "../utils/session";

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
      "X-API-Key": process.env.NEXT_PUBLIC_API_KEY ?? "",
    },
    onError: (error: unknown) => {
      if (!(error instanceof Error)) throw error;
      let userMessage = "Something went wrong. Please try again.";
      try {
        const parsed = JSON.parse(error.message);
        userMessage = parsed.detail ?? error.message;
      } catch {
        userMessage = error.message;
      }
      // Report to Sentry for monitoring (silent — user never sees this)
      Sentry.captureException(error, {
        extra: { userMessage },
      });
      // Show inline error instead of blocking alert
      setChatError(userMessage);
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

      {/* Inline error banner */}
      {chatError && (
        <div className="mx-4 md:mx-8 lg:mx-16 xl:mx-24 2xl:mx-32 mb-2 px-4 py-2 rounded-md bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800 flex items-center justify-between gap-2">
          <p className="text-sm text-red-600 dark:text-red-400">{chatError}</p>
          <button
            onClick={() => setChatError(null)}
            className="text-red-400 hover:text-red-600 dark:hover:text-red-300 text-lg leading-none"
            aria-label="Dismiss error"
          >
            ×
          </button>
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
