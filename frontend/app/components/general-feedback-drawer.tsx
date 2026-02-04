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
const SCREENSHOT_MAX_WIDTH = 1600;
const FLASH_VISIBLE_MS = 140;
const FLASH_EXIT_MS = 420;
const CAPTURE_READY_TIMEOUT_MS = 2500;

export function GeneralFeedbackDrawer({ isOpen, onClose }: GeneralFeedbackDrawerProps) {
  const { backend = "" } = useClientConfig();
  const { show, message, showToast, hideToast } = useToast();

  const [feedback, setFeedback] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isCapturing, setIsCapturing] = useState(false);
  const [deviceId, setDeviceId] = useState("");
  const [screenshotFile, setScreenshotFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [flashMounted, setFlashMounted] = useState(false);
  const [flashVisible, setFlashVisible] = useState(false);
  const [justCaptured, setJustCaptured] = useState(false);

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
    setIsCapturing(false);
    setJustCaptured(false);
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

  const triggerFlash = () => {
    setFlashMounted(true);
    requestAnimationFrame(() => setFlashVisible(true));
    window.setTimeout(() => setFlashVisible(false), FLASH_VISIBLE_MS);
    window.setTimeout(() => setFlashMounted(false), FLASH_EXIT_MS);
  };

  const captureTabScreenshot = async () => {
    if (isCapturing || isSubmitting) return;

    const getDisplayMedia = navigator.mediaDevices?.getDisplayMedia as
      | undefined
      | ((constraints?: unknown) => Promise<MediaStream>);

    if (typeof window !== "undefined") {
      // getDisplayMedia requires a secure context (HTTPS) except for localhost.
      if (!window.isSecureContext) {
        showToast("Screen capture requires HTTPS. Please upload an image instead.");
        pickScreenshot();
        return;
      }

      // Screen capture is typically blocked from inside iframes.
      if (window.top !== window.self) {
        showToast("Screen capture isn't available in embedded views. Please upload an image instead.");
        pickScreenshot();
        return;
      }
    }

    // Some environments disable capture via Permissions Policy.
    const allowsDisplayCapture =
      (document as any)?.permissionsPolicy?.allowsFeature?.("display-capture") ??
      (document as any)?.featurePolicy?.allowsFeature?.("display-capture") ??
      true;
    if (!allowsDisplayCapture) {
      showToast("Screen capture is blocked by browser policy. Please upload an image instead.");
      pickScreenshot();
      return;
    }

    if (!getDisplayMedia) {
      showToast("Screenshot capture isn't supported here. Please upload an image instead.");
      pickScreenshot();
      return;
    }

    setIsCapturing(true);
    try {
      // Browsers will still show a picker; we can only *prefer* the current tab.
      showToast("Select “This tab” to capture a screenshot.");

      let stream: MediaStream;
      try {
        stream = await getDisplayMedia({
          video: {
            cursor: "never",
            frameRate: { ideal: 30, max: 30 },
          },
          audio: false,
          preferCurrentTab: true,
          selfBrowserSurface: "include",
          surfaceSwitching: "exclude",
          systemAudio: "exclude",
        } as any);
      } catch (err: any) {
        // Some browsers reject non-standard constraint keys (e.g. Safari/Firefox).
        if ((err?.name as string | undefined) === "NotAllowedError") {
          throw err;
        }
        stream = await getDisplayMedia({ video: true, audio: false });
      }

      const videoTrack = stream.getVideoTracks?.()[0];
      if (!videoTrack) {
        throw new Error("No video track");
      }

      const displaySurface = (videoTrack.getSettings?.() as any)?.displaySurface as string | undefined;
      if (displaySurface && displaySurface !== "browser") {
        showToast("Tip: choose “This tab” for best results.");
      }

      const video = document.createElement("video");
      video.srcObject = stream;
      video.muted = true;
      video.playsInline = true;

      try {
        await video.play();
      } catch {
        // Some browsers require a short delay before play() succeeds.
        await new Promise((r) => setTimeout(r, 120));
        await video.play();
      }

      const startedAt = Date.now();
      await new Promise<void>((resolve, reject) => {
        const tick = () => {
          const hasFrame = video.readyState >= 2 && video.videoWidth > 0 && video.videoHeight > 0;
          if (hasFrame) {
            resolve();
            return;
          }
          if (Date.now() - startedAt > CAPTURE_READY_TIMEOUT_MS) {
            reject(new Error("Timed out waiting for capture frame"));
            return;
          }
          requestAnimationFrame(tick);
        };
        tick();
      });

      const vw = video.videoWidth || 0;
      const vh = video.videoHeight || 0;
      if (!vw || !vh) {
        throw new Error("Could not read video dimensions");
      }

      const scale = vw > SCREENSHOT_MAX_WIDTH ? SCREENSHOT_MAX_WIDTH / vw : 1;
      const cw = Math.max(1, Math.round(vw * scale));
      const ch = Math.max(1, Math.round(vh * scale));

      const canvas = document.createElement("canvas");
      canvas.width = cw;
      canvas.height = ch;

      const ctx = canvas.getContext("2d");
      if (!ctx) {
        throw new Error("Could not capture screenshot");
      }
      ctx.drawImage(video, 0, 0, cw, ch);

      video.pause();
      video.srcObject = null;
      stream.getTracks().forEach((t) => t.stop());

      const toBlob = (quality: number) =>
        new Promise<Blob>((resolve, reject) => {
          canvas.toBlob(
            (b) => (b ? resolve(b) : reject(new Error("toBlob returned null"))),
            "image/jpeg",
            quality,
          );
        });

      let blob = await toBlob(0.86);
      if (blob.size > MAX_SCREENSHOT_BYTES) {
        blob = await toBlob(0.75);
      }
      if (blob.size > MAX_SCREENSHOT_BYTES) {
        showToast("Screenshot is too large. Try resizing the window and capture again.");
        return;
      }

      setScreenshotFile(new File([blob], `screenshot-${Date.now()}.jpg`, { type: "image/jpeg" }));
      setJustCaptured(true);
      window.setTimeout(() => setJustCaptured(false), 900);
      triggerFlash();
    } catch (err: any) {
      const name = err?.name as string | undefined;
      const msg = (err?.message as string | undefined) ?? "";
      const msgLower = msg.toLowerCase();

      // Chrome sometimes reports "Could not perform screen capture." in these cases.
      if (
        name === "NotReadableError" ||
        msgLower.includes("could not perform screen capture") ||
        msgLower.includes("could not start video source")
      ) {
        showToast("Screen capture is blocked by system permissions. Enable screen recording for your browser and try again.");
        return;
      }

      if (name === "NotAllowedError" || name === "SecurityError") {
        if (msg.toLowerCase().includes("insecure")) {
          showToast("Screen capture requires HTTPS. Please upload an image instead.");
          pickScreenshot();
          return;
        }
        showToast("Screen capture was blocked or cancelled. You can upload an image instead.");
        return;
      }

      if (name === "NotSupportedError") {
        showToast("Screen capture isn't supported in this browser. Please upload an image instead.");
        pickScreenshot();
        return;
      }

      showToast("Could not capture screenshot. Please try again, or upload an image instead.");
    } finally {
      setIsCapturing(false);
    }
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
                        onClick={captureTabScreenshot}
                        disabled={isCapturing}
                        className="h-9 px-3 rounded-lg bg-transparent border-white/15 text-white hover:bg-white/10 hover:text-white"
                      >
                        <Camera className="h-4 w-4 mr-2" />
                        {isCapturing ? "Capturing..." : "Capture screenshot"}
                      </Button>
                    </div>
                  </div>

                  <div className="mt-2 flex items-center justify-between gap-3">
                    <p className="text-xs text-white/55">
                      {isCapturing ? "Choose “This tab” in the browser prompt." : "Capture the current tab, or upload an image."}
                    </p>
                    <button
                      type="button"
                      onClick={pickScreenshot}
                      className="text-xs text-[#FFC328] hover:text-[#FFD155] underline underline-offset-4"
                    >
                      Upload instead
                    </button>
                  </div>

                  {screenshotFile && (
                    <div
                      className={[
                        "mt-4 flex items-center gap-3 rounded-xl border border-white/10 bg-white/5 p-3",
                        "transition-[box-shadow,transform] duration-300 ease-out",
                        justCaptured ? "ring-2 ring-[#FFC328]/60 shadow-[0_0_0_6px_rgba(255,195,40,0.14)]" : "",
                      ].join(" ")}
                    >
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

      {flashMounted && (
        <div
          aria-hidden="true"
          className={[
            "fixed inset-0 z-[11000] pointer-events-none",
            "bg-[radial-gradient(circle_at_center,rgba(255,255,255,0.95),rgba(255,255,255,0)_65%)]",
            "transition-opacity duration-300 ease-out",
            flashVisible ? "opacity-90" : "opacity-0",
          ].join(" ")}
        />
      )}

      <Toast show={show} message={message} onClose={hideToast} />
    </>
  );
}
