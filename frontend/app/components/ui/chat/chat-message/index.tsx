import { Check, Copy, RefreshCw, Pencil } from "lucide-react";

import { Message } from "ai";
import { Fragment, useState } from "react";
import { Button } from "../../button";
import { useCopyToClipboard } from "../hooks/use-copy-to-clipboard";
import {
  ChatHandler,
  DocumentFileData,
  EventData,
  ImageData,
  MessageAnnotation,
  MessageAnnotationType,
  SuggestedQuestionsData,
  ToolData,
  UserLanguageData,
  getAnnotationData,
  getSourceAnnotationData,
} from "../index";
import ChatAvatar from "./chat-avatar";
import { ChatEvents } from "./chat-events";
import { ChatFiles } from "./chat-files";
import { ChatImage } from "./chat-image";
import { ChatSources } from "./chat-sources";
import { SuggestedQuestions } from "./chat-suggestedQuestions";
import ChatTools from "./chat-tools";
import Markdown from "./markdown";
import { UserFeedbackComponent } from "./UserFeedbackComponent";

type ContentDisplayConfig = {
  order: number;
  component: JSX.Element | null;
};

function ChatMessageContent({
  message,
  isLoading,
  append,
}: {
  message: Message;
  isLoading: boolean;
  append: Pick<ChatHandler, "append">["append"];
}) {
  const annotations = message.annotations as MessageAnnotation[] | undefined;
  if (!annotations?.length) return <Markdown content={message.content} />;


  const imageData = getAnnotationData<ImageData>(
    annotations,
    MessageAnnotationType.IMAGE,
  );
  const contentFileData = getAnnotationData<DocumentFileData>(
    annotations,
    MessageAnnotationType.DOCUMENT_FILE,
  );
  const eventData = getAnnotationData<EventData>(
    annotations,
    MessageAnnotationType.EVENTS,
  );

  const sourceData = getSourceAnnotationData(annotations);

  const toolData = getAnnotationData<ToolData>(
    annotations,
    MessageAnnotationType.TOOLS,
  );
  const suggestedQuestionsData = getAnnotationData<SuggestedQuestionsData>(
    annotations,
    MessageAnnotationType.SUGGESTED_QUESTIONS,
  );
  const userLanguageData = getAnnotationData<UserLanguageData>(
    annotations,
    MessageAnnotationType.USER_LANGUAGE,
  );

  const contents: ContentDisplayConfig[] = [
    {
      order: 1,
      component: imageData[0] ? <ChatImage data={imageData[0]} /> : null,
    },
    {
      order: -3,
      component:
        eventData.length > 0 ? (
          <ChatEvents isLoading={isLoading} data={eventData} />
        ) : null,
    },
    {
      order: 2,
      component: contentFileData[0] ? (
        <ChatFiles data={contentFileData[0]} />
      ) : null,
    },
    {
      order: -1,
      component: toolData[0] ? <ChatTools data={toolData[0]} /> : null,
    },
    {
      order: 0,
      component: <Markdown content={message.content} sources={sourceData[0]} />,
    },
    {
      order: 3,
      component: sourceData[0] ? <ChatSources data={sourceData[0]} /> : null,
    },
    {
      order: 4,
      component: suggestedQuestionsData[0] ? (
        <SuggestedQuestions
          questions={suggestedQuestionsData[0]}
          append={append}
        />
      ) : null,
    },
  ];

  return (
    <div className="flex-1 gap-4 flex flex-col min-w-0 max-w-full">
      {contents
        .sort((a, b) => a.order - b.order)
        .map((content, index) => (
          <Fragment key={index}>{content.component}</Fragment>
        ))}
      <div>
      </div>
    </div>
  );
}

export default function ChatMessage({
  chatMessage,
  isLoading,
  append,
  reload,
  showReload,
  messages,
  setMessages,
}: {
  chatMessage: Message;
  isLoading: boolean;
  append: Pick<ChatHandler, "append">["append"];
  reload?: Pick<ChatHandler, "reload">["reload"];
  showReload?: boolean;
  messages?: Message[];
  setMessages?: Pick<ChatHandler, "setMessages">["setMessages"];
}) {

  const { isCopied, copyToClipboard } = useCopyToClipboard({ timeout: 2000 });
  const [isEditing, setIsEditing] = useState(false);
  const [editedContent, setEditedContent] = useState("");
  
  // look for an annotation with the trace_id
  const traceId = (chatMessage.annotations?.find(
    (annotation) => (annotation as MessageAnnotation)?.trace_id) as MessageAnnotation)?.trace_id || "";
  
  const isUser = chatMessage.role === "user";

  // Check if this is the last assistant message
  const isLastMessage = messages && messages.length > 0
    ? messages[messages.length - 1].id === chatMessage.id
    : false;

  const handleEditClick = () => {
    setEditedContent(chatMessage.content);
    setIsEditing(true);
  };
  
  const handleSaveEdit = () => {
    const trimmedContent = editedContent.trim();
    if (trimmedContent && messages && setMessages && append) {
      // Find the index of the current message
      const currentIndex = messages.findIndex(m => m.id === chatMessage.id);
      
      // Remove all messages after (and including) the current message
      const updatedMessages = messages.slice(0, currentIndex);
      setMessages(updatedMessages);
      
      // Submit the edited message as a new message
      append({ role: "user", content: trimmedContent });
    }
    setIsEditing(false);
    setEditedContent("");
  };
  
  const handleCancelEdit = () => {
    setIsEditing(false);
    setEditedContent("");
  };
    
  return (
    <div className={`flex flex-col gap-2 ${isUser ? 'items-end' : 'items-start'}`}>
      {/* User message - dark bubble on right */}
      {isUser && (
        <div className={`group flex flex-col items-end gap-2 ${isEditing ? 'w-full max-w-[90%] sm:max-w-[576px]' : ''}`}>
          {isEditing ? (
            /* Edit mode - inline textarea with full width */
            <div className="w-full bg-[#F0EEE6] dark:bg-[#2a2a2a] border border-[rgba(31,30,29,0.15)] dark:border-[rgba(252,252,252,0.1)] rounded-2xl p-4">
              <textarea
                value={editedContent}
                onChange={(e) => setEditedContent(e.target.value)}
                className="w-full bg-transparent border-none text-[#3D3D3A] dark:text-white placeholder:text-[#73726C] dark:placeholder:text-[#B5B5B5] focus:outline-none text-sm sm:text-[15.75px] leading-[24px] sm:leading-[28px] resize-none min-h-[50px] max-h-[200px]"
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSaveEdit();
                  }
                }}
              />
              <div className="flex items-center justify-end gap-3 mt-3">
                <Button
                  onClick={handleCancelEdit}
                  variant="ghost"
                  className="text-[#73726C] dark:text-[#B5B5B5] bg-[#D1CFC2] hover:bg-[#B3B1A0] hover:text-[#3D3D3A] dark:text-[#3E3C33] dark:hover:text-white text-sm"
                >
                  Cancel
                </Button>
                <Button
                  onClick={handleSaveEdit}
                  className="bg-[#FFC328] dark:bg-white text-[#FF346] dark:text-black hover:bg-[#FFD255] dark:hover:bg-gray-200 text-sm px-6"
                >
                  Save
                </Button>
              </div>
            </div>
          ) : (
            /* Normal message display - hugs content */
            <>
              <div className="bg-[#E9E7E1] dark:bg-[#242628] text-[#3D3D3A] dark:text-[#FCFCFC] px-4 sm:px-[17px] py-3 sm:py-[11px] rounded-[24px] rounded-br-[8px] max-w-[90%] sm:max-w-[576px] border border-[rgba(31,30,29,0.12)] dark:border-[rgba(252,252,252,0.06)] overflow-wrap-anywhere">
                <p className="text-sm sm:text-[15.75px] leading-[24px] sm:leading-[28px] tracking-[-0.1px] break-words overflow-wrap-anywhere">{chatMessage.content}</p>
              </div>
              
              {/* Action buttons for user message - only visible on hover */}
              <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                <Button
                  onClick={handleEditClick}
                  size="icon"
                  variant="ghost"
                  className="h-6 w-6 rounded-full hover:bg-[rgba(181,181,181,0.15)] transition-colors"
                  title="Edit"
                >
                  <Pencil className="h-3.5 w-3.5 text-[#3D3D3A] dark:text-[#FCFCFC] hover:text-[#1F1E1D] dark:hover:text-white transition-colors" />
                </Button>
                <Button
                  onClick={() => copyToClipboard(chatMessage.content)}
                  size="icon"
                  variant="ghost"
                  className={`h-6 w-6 rounded-full hover:bg-[rgba(181,181,181,0.15)] transition-colors ${isCopied ? 'pointer-events-none' : ''}`}
                  title="Copy"
                >
                  {isCopied ? (
                    <Check className="h-3.5 w-3.5 text-gray-700 dark:text-[#FCFCFC]" />
                  ) : (
                    <Copy className="h-3.5 w-3.5 text-gray-700 dark:text-[#FCFCFC] hover:text-gray-900 dark:hover:text-white transition-colors" />
                  )}
                </Button>
              </div>
            </>
          )}
        </div>
      )}
      
      {/* Bot message - left aligned with inline action icons */}
      {!isUser && (
        <div className="w-full">
          <div className="flex items-start gap-3">
            {/* Avatar on the left */}
            <div className="mt-1">
              <ChatAvatar role={chatMessage.role} />
            </div>

            {/* Message content */}
            <div className="flex-1 min-w-0 max-w-full">
              <ChatMessageContent
                message={chatMessage}
                isLoading={isLoading}
                append={append}
              />

              {/* Action buttons - inline after message content */}
              {!isLoading && (
                <div className="flex items-start gap-1 mt-1 mb-4">
                  <Button
                    onClick={() => copyToClipboard(chatMessage.content)}
                    size="icon"
                    variant="ghost"
                    className={`h-6 w-6 rounded-full hover:bg-[rgba(181,181,181,0.15)] transition-colors ${isCopied ? 'pointer-events-none' : ''}`}
                    title="Copy"
                  >
                    {isCopied ? (
                      <Check className="h-4 w-4 text-gray-700 dark:text-[#FCFCFC]" />
                    ) : (
                      <Copy className="h-4 w-4 text-gray-700 dark:text-[#FCFCFC] hover:text-gray-900 dark:hover:text-white transition-colors" />
                    )}
                  </Button>
                  <UserFeedbackComponent traceId={traceId} isLastMessage={isLastMessage} />
                  {showReload && reload && (
                    <Button
                      onClick={reload}
                      size="icon"
                      variant="ghost"
                      className="h-6 w-6 rounded-full hover:bg-[rgba(181,181,181,0.15)] transition-colors"
                      title="Regenerate"
                    >
                      <RefreshCw className="h-3.5 w-3.5 text-gray-700 dark:text-[#FCFCFC] hover:text-gray-900 dark:hover:text-white transition-colors" />
                    </Button>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
