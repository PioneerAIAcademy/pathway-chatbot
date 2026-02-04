import { Button } from "../../button";
import { ArrowUp, ThumbsDown, ThumbsUp } from "lucide-react";
import { useLayoutEffect, useState, useRef, useEffect } from "react";
import { FeedbackValue, sendUserFeedback } from "./thumb_request";
import { useClientConfig } from "../hooks/use-config";
import { Toast, useToast } from "../../toast";
import { cn } from "../../lib/utils";
import styles from "./UserFeedbackComponent.module.css";

type UserFeedbackComponentProps = { traceId: string };

const BORDER_ANIMATION_MS = 680;
const BUTTON_REVEAL_MS = 520;
const FOCUS_MS = 600;
const CLOSE_ANIMATION_MS = 240;
const MAX_COMMENT_LENGTH = 300;
const MOBILE_POPOVER_MARGIN_PX = 16;

export function UserFeedbackComponent({ traceId }: UserFeedbackComponentProps) {
    const { backend = "" } = useClientConfig();
    const { show, message, showToast, hideToast } = useToast();

    const rootRef = useRef<HTMLDivElement>(null);
    const [submittedFeedback, setSubmittedFeedback] = useState<FeedbackValue>(FeedbackValue.EMPTY);
    const [showInput, setShowInput] = useState(false);
    const [comment, setComment] = useState("");
    const [isAnimating, setIsAnimating] = useState(false);
    const [showButtons, setShowButtons] = useState(false);
    const [isClosing, setIsClosing] = useState(false);
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const thumbsDownButtonRef = useRef<HTMLButtonElement>(null);
    const buttonRowRef = useRef<HTMLDivElement>(null);
    const popoverAnchorRef = useRef<HTMLDivElement>(null);
    const popoverRef = useRef<HTMLDivElement>(null);
    const animationTimers = useRef<number[]>([]);
    const feedbackBeforeOpenRef = useRef<FeedbackValue>(FeedbackValue.EMPTY);
    const [reservedSpacePx, setReservedSpacePx] = useState(0);
    const [mobilePopoverOffsetX, setMobilePopoverOffsetX] = useState(0);
    const [mobilePopoverMaxWidthPx, setMobilePopoverMaxWidthPx] = useState<number | null>(null);

    const thumbsUpActive = submittedFeedback === FeedbackValue.GOOD;
    const thumbsDownActive = submittedFeedback === FeedbackValue.BAD;

    const clearTimers = () => {
        animationTimers.current.forEach((timer) => window.clearTimeout(timer));
        animationTimers.current = [];
    };

    useEffect(() => {
        return () => {
            clearTimers();
        };
    }, []);

    useLayoutEffect(() => {
        if (!showInput) {
            setReservedSpacePx(0);
            return;
        }

        const row = buttonRowRef.current;
        const popover = popoverRef.current;
        if (!row || !popover) {
            return;
        }

        const measure = () => {
            const rowRect = row.getBoundingClientRect();
            const popoverRect = popover.getBoundingClientRect();
            const needed = Math.max(0, popoverRect.bottom - rowRect.bottom);
            setReservedSpacePx((prev) => (Math.abs(prev - needed) > 1 ? Math.ceil(needed) : prev));
        };

        measure();
        const raf = window.requestAnimationFrame(measure);
        return () => window.cancelAnimationFrame(raf);
    }, [showInput, showButtons]);

    // Mobile-only: keep the popover within the viewport (prevents horizontal scrolling).
    useLayoutEffect(() => {
        if (!showInput || isClosing) {
            return;
        }

        const popover = popoverRef.current;
        const anchor = popoverAnchorRef.current;
        const actionsRow = rootRef.current?.parentElement;
        if (!popover || !anchor || !actionsRow) {
            return;
        }

        const isMobile = window.matchMedia("(max-width: 639px)").matches;
        if (!isMobile) {
            setMobilePopoverOffsetX(0);
            setMobilePopoverMaxWidthPx(null);
            return;
        }

        const adjust = () => {
            const anchorRect = anchor.getBoundingClientRect();
            const rowRect = actionsRow.getBoundingClientRect();

            // Mobile: anchor at thumbs-down, but align the popover's left edge with the action
            // row (copy icon). To avoid horizontal scrolling, constrain the popover width so it
            // can fit to the right of that aligned start point.
            const desiredLeft = Math.max(rowRect.left, MOBILE_POPOVER_MARGIN_PX);
            const offset = desiredLeft - anchorRect.left;
            setMobilePopoverOffsetX(Math.round(offset));

            const maxWidth = Math.floor(window.innerWidth - desiredLeft - MOBILE_POPOVER_MARGIN_PX);
            setMobilePopoverMaxWidthPx(maxWidth > 0 ? maxWidth : null);
        };

        adjust();
        const raf = window.requestAnimationFrame(adjust);
        window.addEventListener("resize", adjust);
        return () => {
            window.cancelAnimationFrame(raf);
            window.removeEventListener("resize", adjust);
        };
    }, [showInput, showButtons, isClosing]);

    const handleUserFeedback = async (traceId: string, value: FeedbackValue, feedbackComment?: string) => {
        const ok = await sendUserFeedback(backend, traceId, value, feedbackComment);
        if (ok && value !== FeedbackValue.EMPTY) {
            showToast("Thanks for your feedback!");
        }
    };

    const closeInput = (opts?: { revertFeedback?: boolean }) => {
        clearTimers();
        if (!showInput) {
            setIsAnimating(false);
            return;
        }
        if (opts?.revertFeedback) {
            setSubmittedFeedback(feedbackBeforeOpenRef.current);
        }
        setIsClosing(true);
        const thumbsDownButton = thumbsDownButtonRef.current;
        if (thumbsDownButton) {
            try {
                thumbsDownButton.focus({ preventScroll: true });
            } catch {
                thumbsDownButton.focus();
            }
        }
        animationTimers.current.push(window.setTimeout(() => {
            setShowInput(false);
            setShowButtons(false);
            setComment("");
            setIsAnimating(false);
            setIsClosing(false);
            setMobilePopoverOffsetX(0);
            setMobilePopoverMaxWidthPx(null);
        }, CLOSE_ANIMATION_MS));
    };

    const handleThumbsDown = () => {
        if (isClosing) {
            clearTimers();
            setIsClosing(false);
            setSubmittedFeedback(FeedbackValue.BAD);
            return;
        }

        if (showInput) {
            // Closing/canceling feedback input
            closeInput({ revertFeedback: true });
            return;
        }

        // Opening feedback input
        feedbackBeforeOpenRef.current = submittedFeedback;
        setSubmittedFeedback(FeedbackValue.BAD);
        if (window.matchMedia("(max-width: 639px)").matches) {
            const anchor = popoverAnchorRef.current;
            const actionsRow = rootRef.current?.parentElement;
            if (anchor && actionsRow) {
                const rowRect = actionsRow.getBoundingClientRect();
                const anchorRect = anchor.getBoundingClientRect();
                const desiredLeft = Math.max(rowRect.left, MOBILE_POPOVER_MARGIN_PX);
                setMobilePopoverOffsetX(Math.round(desiredLeft - anchorRect.left));

                const maxWidth = Math.floor(window.innerWidth - desiredLeft - MOBILE_POPOVER_MARGIN_PX);
                setMobilePopoverMaxWidthPx(maxWidth > 0 ? maxWidth : null);
            } else {
                setMobilePopoverOffsetX(0);
                setMobilePopoverMaxWidthPx(null);
            }
        } else {
            setMobilePopoverOffsetX(0);
            setMobilePopoverMaxWidthPx(null);
        }
        clearTimers();
        setShowInput(true);
        setIsAnimating(true);
        setShowButtons(false);
        setIsClosing(false);
        
        // Trigger border animation, then show buttons
        animationTimers.current.push(window.setTimeout(() => {
            setShowButtons(true);
        }, BUTTON_REVEAL_MS));

        animationTimers.current.push(window.setTimeout(() => {
            setIsAnimating(false);
        }, BORDER_ANIMATION_MS));

        animationTimers.current.push(window.setTimeout(() => {
            const textarea = textareaRef.current;
            if (!textarea) {
                return;
            }
            try {
                textarea.focus({ preventScroll: true });
            } catch {
                textarea.focus();
            }
        }, FOCUS_MS));
    };

    const handleSubmit = async () => {
        await handleUserFeedback(traceId, FeedbackValue.BAD, comment.trim() || undefined);
        setSubmittedFeedback(FeedbackValue.BAD);
        closeInput();
    };

    const handleCancel = () => {
        closeInput({ revertFeedback: true });
    };

    const handleThumbsUp = async () => {
        const nextValue = thumbsUpActive ? FeedbackValue.EMPTY : FeedbackValue.GOOD;
        setSubmittedFeedback(nextValue);
        setComment("");
        setShowButtons(false);
        setIsAnimating(false);
        setIsClosing(false);
        setShowInput(false);
        setMobilePopoverOffsetX(0);
        setMobilePopoverMaxWidthPx(null);
        clearTimers();
        // Passing an empty string clears any previous "bad" comment when switching to Good.
        await handleUserFeedback(traceId, nextValue, "");
    };

    return (
        <div ref={rootRef} className="flex flex-col items-start">
            <div ref={buttonRowRef} className="flex items-start gap-1">
                <Button
                    size="icon"
                    variant="ghost"
                    className="h-6 w-6 rounded-full hover:bg-[rgba(181,181,181,0.15)] transition-colors"
                    title="Love this"
                    onClick={handleThumbsUp}
                >
                    <ThumbsUp 
                        fill={thumbsUpActive ? "#22c55e" : "none"} 
                        className="h-3.5 w-3.5 text-gray-700 dark:text-[#FCFCFC] hover:text-green-600 dark:hover:text-green-500 transition-colors" 
                        strokeWidth={thumbsUpActive ? 0 : 2} 
                    />
                </Button>
                
                <div ref={popoverAnchorRef} className="relative">
                    <Button
                        size="icon"
                        variant="ghost"
                        className="h-6 w-6 rounded-full hover:bg-[rgba(181,181,181,0.15)] transition-colors"
                        title="Needs improvement"
                        onClick={handleThumbsDown}
                        ref={thumbsDownButtonRef}
                    >
                        <ThumbsDown 
                            fill={thumbsDownActive ? "#E18158" : "none"} 
                            className="h-3.5 w-3.5 text-gray-700 dark:text-[#FCFCFC] hover:text-gray-900 dark:hover:text-white transition-colors" 
                            strokeWidth={thumbsDownActive ? 0 : 2} 
                        />
                    </Button>

                    {showInput && (
                        <div
                            className="absolute top-8 left-0 z-10"
                            style={{
                                transform: mobilePopoverOffsetX ? `translateX(${mobilePopoverOffsetX}px)` : undefined,
                            }}
                        >
                            <div
                                ref={popoverRef}
                                className={cn(
                                    styles.popover,
                                    "w-[clamp(18rem,65vw,44rem)] max-w-[calc(100vw-2.5rem)]",
                                )}
                                style={mobilePopoverMaxWidthPx ? { maxWidth: `${mobilePopoverMaxWidthPx}px` } : undefined}
                                data-state={isClosing ? "closing" : "open"}
                            >
                            {/* Feedback UI */}
                            <div className="flex flex-col">
                                <div
                                    className={cn(
                                        styles.field,
                                        "relative rounded-2xl overflow-hidden text-[#D4A24A] dark:text-[#D4A24A]",
                                    )}
                                    data-animating={isAnimating ? "true" : "false"}
                                    data-closing={isClosing ? "true" : "false"}
                                >
                                    <svg
                                        className={cn(styles.drawBorder, "pointer-events-none")}
                                        aria-hidden="true"
                                        width="100%"
                                        height="100%"
                                    >
                                        <rect
                                            className={styles.drawBorderRect}
                                            pathLength="1"
                                            x="0"
                                            y="0"
                                            width="100%"
                                            height="100%"
                                            rx="14"
                                            ry="14"
                                        />
                                    </svg>

                                    <div
                                        className={cn(
                                            styles.fieldInner,
                                            "bg-[#F0EEE6] dark:bg-[#242628] px-4 py-3.5",
                                        )}
                                    >
                                        <textarea
                                            ref={textareaRef}
                                            value={comment}
                                            onChange={(e) => setComment(e.target.value)}
                                            placeholder="How could this be better? (optional)"
                                            maxLength={MAX_COMMENT_LENGTH}
                                            rows={2}
                                            className="w-full min-h-[72px] bg-transparent border-none text-[#141413] dark:text-white placeholder:text-[#73726C] dark:placeholder:text-[#B5B5B5] focus-visible:ring-0 focus-visible:ring-offset-0 focus:outline-none text-sm resize-none max-h-[160px] leading-6"
                                        />
                                    </div>
                                </div>

                                {/* Footer with fade-in animation */}
                                {showButtons && (
                                    <div
                                        className={cn(
                                            styles.footer,
                                            "flex items-center justify-end gap-3 mt-2",
                                        )}
                                    >
                                        <span className="text-xs text-[#73726C] dark:text-[#B5B5B5] tabular-nums mr-1">
                                            {MAX_COMMENT_LENGTH - comment.length}
                                        </span>
                                        <Button
                                            variant="ghost"
                                            size="sm"
                                            onClick={handleCancel}
                                            className="h-8 px-3 bg-transparent hover:bg-transparent text-[#73726C] dark:text-[#B5B5B5] hover:text-[#141413] dark:hover:text-white"
                                        >
                                            Cancel
                                        </Button>
                                        <Button
                                            size="sm"
                                            onClick={handleSubmit}
                                            className="h-8 px-3 rounded-xl bg-[#FFC328] hover:bg-[#FFD155] text-[#454540] dark:text-black flex items-center gap-2"
                                        >
                                            Submit
                                            <ArrowUp className="h-4 w-4" />
                                        </Button>
                                    </div>
                                )}
                            </div>
                            </div>
                        </div>
                    )}
                </div>
            </div>

            {/* Reserve vertical space so the popover doesn't overlap messages below it */}
            {showInput && (
                <div
                    aria-hidden="true"
                    className="transition-[height] duration-200 ease-out"
                    style={{ height: reservedSpacePx }}
                />
            )}

            <Toast show={show} message={message} onClose={hideToast} />
        </div>
    );
}
