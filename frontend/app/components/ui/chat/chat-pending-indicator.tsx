import ChatAvatar from "./chat-message/chat-avatar";

export default function ChatPendingIndicator() {
  return (
    <div className="w-full">
      <div className="flex items-start gap-3">
        <div className="mt-1">
          <ChatAvatar role="assistant" />
        </div>
        <div className="flex-1 min-w-0 max-w-full">
          <div className="text-xs text-[#73726C] dark:text-[#C2C0B6] animate-pulse">
            Thinking...
          </div>
        </div>
      </div>
    </div>
  );
}

