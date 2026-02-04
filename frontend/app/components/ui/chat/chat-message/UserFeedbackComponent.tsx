import { Button } from "../../button";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";
import { FeedbackValue, sendUserFeedback } from "./thumb_request";
import { useClientConfig } from "../hooks/use-config";
import { Toast, useToast } from "../../toast";

export function UserFeedbackComponent(props: { traceId: string }) {
    const { backend = "" } = useClientConfig();
    const { show, message, showToast, hideToast } = useToast();

    const handleUserFeedback = async (traceId: string, value: FeedbackValue) => {
        try {
            await sendUserFeedback(backend, traceId, value);
            if (value !== FeedbackValue.EMPTY) {
                showToast("Thanks for your feedback!");
            }
        } catch {
            showToast("Could not send feedback. Please try again.");
        }
    };

    const [ThumbsUpActive, setThumbsUpActive] = useState(false);
    const [ThumbsDownActive, setThumbsDownActive] = useState(false);

    return (
        <>
            <Button
                size="icon"
                variant="ghost"
                className="h-6 w-6 rounded-full hover:bg-[rgba(181,181,181,0.15)] transition-colors"
                title="Love this"
                onClick={() => {
                    setThumbsUpActive(!ThumbsUpActive);
                    setThumbsDownActive(false);
                    handleUserFeedback(props.traceId, !ThumbsUpActive ? FeedbackValue.GOOD : FeedbackValue.EMPTY);
                }}
            >
                <ThumbsUp 
                    fill={ThumbsUpActive ? "#22c55e" : "none"} 
                    className="h-3.5 w-3.5 text-gray-700 dark:text-[#FCFCFC] hover:text-green-600 dark:hover:text-green-500 transition-colors" 
                    strokeWidth={ThumbsUpActive ? 0 : 2} 
                />
            </Button>
            <Button
                size="icon"
                variant="ghost"
                className="h-6 w-6 rounded-full hover:bg-[rgba(181,181,181,0.15)] transition-colors"
                title="Needs improvement"
                onClick={() => {
                    setThumbsDownActive(!ThumbsDownActive);
                    setThumbsUpActive(false);
                    handleUserFeedback(props.traceId, !ThumbsDownActive ? FeedbackValue.BAD : FeedbackValue.EMPTY);
                }}
            >
                <ThumbsDown 
                    fill={ThumbsDownActive ? "#E18158" : "none"} 
                    className="h-3.5 w-3.5 text-gray-700 dark:text-[#FCFCFC] hover:text-gray-900 dark:hover:text-white transition-colors" 
                    strokeWidth={ThumbsDownActive ? 0 : 2} 
                />
            </Button>
            <Toast show={show} message={message} onClose={hideToast} />
        </>
    );
}
