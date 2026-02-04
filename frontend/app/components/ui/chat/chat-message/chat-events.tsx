import { Loader2 } from "lucide-react";
import { EventData } from "../index";

/**
 * ChatEvents component displays real-time status indicators during RAG processing.
 * Shows inline status with randomized messages that auto-disappear when response starts.
 */
export function ChatEvents({
  data,
  isLoading,
  hasResponseText,
}: {
  data: EventData[];
  isLoading: boolean;
  hasResponseText: boolean;
}) {
  // Get the latest status message
  const latestMessage = data.length > 0 ? data[data.length - 1].title : "";

  // Show status ONLY while loading AND before response text appears
  const showStatus = isLoading && !!latestMessage && !hasResponseText;

  if (!showStatus) return null;

  return (
    <div className="flex items-center gap-2 text-xs text-[#73726C] dark:text-[#C2C0B6]">
      <Loader2 className="h-4 w-4 animate-spin" />
      <span>{latestMessage}</span>
    </div>
  );
}
