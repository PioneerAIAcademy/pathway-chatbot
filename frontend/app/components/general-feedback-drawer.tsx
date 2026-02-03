"use client";

import { Drawer } from "vaul";
import { useEffect, useMemo, useRef, useState } from "react";
import { Camera, X } from "lucide-react";

import { Button } from "./ui/button";
import { Toast, useToast } from "./ui/toast";
import { useClientConfig } from "./ui/chat/hooks/use-config";
import { getDeviceId, getSessionId } from "../utils/session";

type GeneralFeedbackDrawerProps = {
  isOpen: boolean;
  onClose: () => void;
};

const MAX_FEEDBACK_LENGTH = 1000;
const MAX_SCREENSHOT_BYTES = 6 * 1024 * 1024; // 6MB

export function GeneralFeedbackDrawer({ isOpen, onClose }: GeneralFeedbackDrawerProps) {
  const { backend = "" } = useClientConfig();
  const { show, message, showToast, hideToast } = useToast();

  const [feedback, setFeedback] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [deviceId, setDeviceId] = useState("");
  const [screenshotFile, setScreenshotFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    getDeviceId().then(setDeviceId);
  }, []);

  const screenshotPreviewUrl = useMemo(() => {
    if (!screenshotFile) return "";
    return URL.createObjectURL(screenshotFile);
  }, [screenshotFile]);

  useEffect(() => {
    return () => {
      if (screenshotPreviewUrl) URL.revokeObjectURL(screenshotPreviewUrl);
    };
  }, [screenshotPreviewUrl]);

  const resetState = () => {
    setFeedback("");
    setScreenshotFile(null);
    setIsSubmitting(false);
  };

  const handleClose = () => {
    resetState();
    onClose();
  };

  const pickScreenshot = () => {
    fileInputRef.current?.click();
  };

  const onFileChange = (file: File | null) => {
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      showToast("Please choose an image file.");
      return;
    }
    if (file.size > MAX_SCREENSHOT_BYTES) {
      showToast("That image is too large. Please choose one under 6MB.");
      return;
    }
    setScreenshotFile(file);
  };

  const handleSubmit = async () => {
    const trimmed = feedback.trim();
    if (!trimmed) {
      showToast("Please describe your feedback before sending.");
      return;
    }

    setIsSubmitting(true);
    try {
      const form = new FormData();
      form.append("feedback", trimmed);
      if (screenshotFile) {
        form.append("screenshot", screenshotFile);
      }

      const res = await fetch(`${backend}/api/chat/feedback/general`, {
        method: "POST",
        headers: {
          "X-Session-ID": getSessionId(),
          "X-Device-ID": deviceId,
        },
        body: form,
      });

      if (!res.ok) {
        throw new Error("Failed to submit feedback");
      }

      showToast("Thanks for your feedback!");
      handleClose();
    } catch {
      showToast("Could not send feedback. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <>
      <Drawer.Root open={isOpen} onOpenChange={(open) => !open && handleClose()} direction="right">
        <Drawer.Portal>
          <Drawer.Overlay className="fixed inset-0 bg-black/40 z-50" />
          <Drawer.Content className="fixed bottom-0 right-0 top-0 z-50 flex outline-none w-full sm:max-w-[460px]">
            <div className="flex-1 bg-[#111213] text-white shadow-2xl border-l border-white/10">
              {/* Header */}
              <div className="px-6 pt-6 pb-5 border-b border-white/10">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <Drawer.Title className="text-[22px] font-semibold leading-7">
                      Send feedback
                    </Drawer.Title>
                    <Drawer.Description className="mt-1 text-sm text-white/70">
                      Help us improve the BYU Pathway Missionary Assistant. Share what happened and what you expected.
                    </Drawer.Description>
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={handleClose}
                    className="h-8 w-8 rounded-full hover:bg-white/10 text-white"
                    title="Close"
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              </div>

              {/* Body */}
              <div className="px-6 py-6 flex flex-col gap-6 overflow-y-auto">
                <div>
                  <label htmlFor="general-feedback-text" className="block text-sm font-medium text-white/90">
                    Describe your feedback (required)
                  </label>
                  <div className="mt-2">
                    <textarea
                      id="general-feedback-text"
                      value={feedback}
                      onChange={(e) => setFeedback(e.target.value)}
                      placeholder="Tell us what prompted this feedback..."
                      maxLength={MAX_FEEDBACK_LENGTH}
                      rows={7}
                      className="w-full rounded-xl bg-white/5 border border-white/10 px-4 py-3 text-sm leading-6 text-white placeholder:text-white/40 focus:outline-none focus:ring-2 focus:ring-[#FFC328]/60 focus:border-[#FFC328]/40 resize-none"
                    />
                  </div>
                  <div className="mt-2 flex items-center justify-between gap-4">
                    <p className="text-xs text-white/55">
                      Please don&apos;t include sensitive information.
                    </p>
                    <p className="text-xs text-white/55 tabular-nums">
                      {feedback.length}/{MAX_FEEDBACK_LENGTH}
                    </p>
                  </div>
                </div>

                <div className="border-t border-white/10 pt-5">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <h3 className="text-sm font-medium text-white/90">Screenshot (optional)</h3>
                      <p className="mt-1 text-xs text-white/55">
                        A screenshot helps us understand what you were seeing.
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept="image/*"
                        className="hidden"
                        onChange={(e) => onFileChange(e.target.files?.[0] ?? null)}
                      />
                      <Button
                        type="button"
                        variant="outline"
                        onClick={pickScreenshot}
                        className="h-9 px-3 rounded-lg bg-transparent border-white/15 text-white hover:bg-white/10 hover:text-white"
                      >
                        <Camera className="h-4 w-4 mr-2" />
                        Add screenshot
                      </Button>
                    </div>
                  </div>

                  {screenshotFile && (
                    <div className="mt-4 flex items-center gap-3 rounded-xl border border-white/10 bg-white/5 p-3">
                      <div className="h-12 w-12 rounded-lg overflow-hidden bg-black/20 border border-white/10 flex-shrink-0">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={screenshotPreviewUrl} alt="Screenshot preview" className="h-full w-full object-cover" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm text-white/90 truncate">{screenshotFile.name}</p>
                        <p className="text-xs text-white/55 tabular-nums">
                          {(screenshotFile.size / (1024 * 1024)).toFixed(1)} MB
                        </p>
                      </div>
                      <Button
                        type="button"
                        variant="ghost"
                        onClick={() => setScreenshotFile(null)}
                        className="h-8 px-2 rounded-lg hover:bg-white/10 text-white/80 hover:text-white"
                        title="Remove screenshot"
                      >
                        Remove
                      </Button>
                    </div>
                  )}
                </div>
              </div>

              {/* Footer */}
              <div className="px-6 py-5 border-t border-white/10 flex items-center gap-3">
                <Button
                  type="button"
                  variant="outline"
                  onClick={handleClose}
                  disabled={isSubmitting}
                  className="flex-1 h-10 rounded-xl bg-transparent border-white/15 text-white hover:bg-white/10 hover:text-white"
                >
                  Cancel
                </Button>
                <Button
                  type="button"
                  onClick={handleSubmit}
                  disabled={isSubmitting || !feedback.trim()}
                  className="flex-1 h-10 rounded-xl bg-[#FFC328] hover:bg-[#FFD155] text-[#454540] font-semibold"
                >
                  {isSubmitting ? "Sending..." : "Send"}
                </Button>
              </div>
            </div>
          </Drawer.Content>
        </Drawer.Portal>
      </Drawer.Root>

      <Toast show={show} message={message} onClose={hideToast} />
    </>
  );
}

