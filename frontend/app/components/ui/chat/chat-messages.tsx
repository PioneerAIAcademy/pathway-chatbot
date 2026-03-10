import { useEffect, useRef, useState } from "react";

import { Button } from "../button";
import ChatMessage from "./chat-message";
import { ChatHandler } from "./chat.interface";
import ChatPendingIndicator from "./chat-pending-indicator";
import { useClientConfig } from "./hooks/use-config";

export default function ChatMessages(
  props: Pick<
    ChatHandler,
    "messages" | "isLoading" | "reload" | "stop" | "append" | "setMessages"
  >,
) {
  const { backend } = useClientConfig();
  const [starterQuestions, setStarterQuestions] = useState<string[]>();

  const scrollableChatContainerRef = useRef<HTMLDivElement>(null);
  const messageLength = props.messages.length;
  const lastMessage = props.messages[messageLength - 1];

  const scrollToBottom = () => {
    if (scrollableChatContainerRef.current) {
      scrollableChatContainerRef.current.scrollTop =
        scrollableChatContainerRef.current.scrollHeight;
    }
  };

  const isLastMessageFromAssistant =
    messageLength > 0 && lastMessage?.role !== "user";

  // `isPending` indicate
  // that stream response is not yet received from the server,
  // so we show a loading indicator to give a better UX.
  const isPending = props.isLoading && !isLastMessageFromAssistant;

  useEffect(() => {
    scrollToBottom();
  }, [messageLength, lastMessage]);

  useEffect(() => {
    if (!starterQuestions) {
      fetch(`${backend}/api/v1/chat/config`)
        .then((response) => response.json())
        .then((data) => {
          if (data?.starterQuestions) {
            setStarterQuestions(data.starterQuestions);
          }
        })
        .catch((error) => console.error("Error fetching config", error));
    }
  }, [starterQuestions, backend]);

  return (
    <div
      className="flex-1 w-full"
      ref={scrollableChatContainerRef}
    >
      <div className="flex flex-col gap-6">
        {props.messages.map((m, i) => {
          const isLoadingMessage = i === messageLength - 1 && props.isLoading;
          const isLastMessage = i === messageLength - 1;
          const showReloadIcon = isLastMessage && !props.isLoading && m.role !== "user";
          return (
            <ChatMessage
              key={m.id}
              chatMessage={m}
              isLoading={isLoadingMessage}
              append={props.append!}
              reload={props.reload}
              showReload={showReloadIcon}
              messages={props.messages}
              setMessages={props.setMessages}
            />
          );
        })}
        {isPending && (
          <ChatPendingIndicator />
        )}
      </div>
      {!messageLength && starterQuestions?.length && props.append && (
        <div className="w-full mt-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {starterQuestions.map((question, i) => (
              <Button
                variant="outline"
                key={i}
                onClick={() =>
                  props.append!({ role: "user", content: question })
                }
                className="border-[#242628] dark:border-[rgba(252,252,252,0.06)] bg-transparent hover:bg-[rgba(252,252,252,0.05)] text-white"
              >
                {question}
              </Button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
