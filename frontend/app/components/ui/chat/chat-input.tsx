import { JSONValue } from "ai";
import { Button } from "../button";
import { DocumentPreview } from "../document-preview";
import FileUploader from "../file-uploader";
import { Input } from "../input";
import UploadImagePreview from "../upload-image-preview";
import { ChatHandler } from "./chat.interface";
import { useFile } from "./hooks/use-file";
import { LlamaCloudSelector } from "./widgets/LlamaCloudSelector";
import { useRef, useEffect } from "react";

const ALLOWED_EXTENSIONS = ["png", "jpg", "jpeg", "csv", "pdf", "txt", "docx"];

export default function ChatInput(
  props: Pick<
    ChatHandler,
    | "isLoading"
    | "input"
    | "onFileUpload"
    | "onFileError"
    | "handleSubmit"
    | "handleInputChange"
    | "messages"
    | "setInput"
    | "append"
    | "stop"
  > & {
    requestParams?: any;
    setRequestData?: React.Dispatch<any>;
    isAcmMode?: boolean;
    isAcmChecked?: boolean;
    setIsAcmChecked?: (checked: boolean) => void;
  },
) {
  const {
    imageUrl,
    setImageUrl,
    uploadFile,
    files,
    removeDoc,
    reset,
    getAnnotations,
  } = useFile();

  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  // Reset the textarea's inline height when the input becomes empty
  useEffect(() => {
    if (!props.input && textareaRef.current) {
      textareaRef.current.style.height = '';
    }
  }, [props.input]);

  // default submit function does not handle including annotations in the message
  // so we need to use append function to submit new message with annotations
  const handleSubmitWithAnnotations = (
    e: React.FormEvent<HTMLFormElement>,
    annotations: JSONValue[] | undefined,
  ) => {
    e.preventDefault();
    props.append!({
      content: props.input,
      role: "user",
      createdAt: new Date(),
      annotations,
    });
    props.setInput!("");
    // reset textarea height after submit
    if (textareaRef.current) {
      textareaRef.current.style.height = '';
    }
  };

  const onSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    const annotations = getAnnotations();
    if (annotations.length) {
      handleSubmitWithAnnotations(e, annotations);
      return reset();
    }
    props.handleSubmit(e);
    // reset textarea height after normal submit
    if (textareaRef.current) {
      textareaRef.current.style.height = '';
    }
  };

  // const handleUploadFile = async (file: File) => {
  //   if (imageUrl || files.length > 0) {
  //     alert("You can only upload one file at a time.");
  //     return;
  //   }
  //   try {
  //     await uploadFile(file, props.requestParams);
  //     props.onFileUpload?.(file);
  //   } catch (error: any) {
  //     const onFileUploadError = props.onFileError || window.alert;
  //     onFileUploadError(error.message);
  //   }
  // };

  return (
    <form
      onSubmit={onSubmit}
      className="w-full"
    >
      {imageUrl && (
        <UploadImagePreview url={imageUrl} onRemove={() => setImageUrl(null)} />
      )}
      {files.length > 0 && (
        <div className="flex gap-4 w-full overflow-auto py-2">
          {files.map((file) => (
            <DocumentPreview
              key={file.id}
              file={file}
              onRemove={() => removeDoc(file)}
            />
          ))}
        </div>
      )}
      <div className="w-full bg-white dark:bg-[#242628] rounded-3xl px-4 py-3 border border-[rgba(31,30,29,0.15)] dark:border-[rgba(252,252,252,0.06)]">
        {/* Top row - Text Input */}
        <div className="relative flex items-center w-full mb-3">
          <textarea
            ref={textareaRef}
            autoFocus
            name="message"
            placeholder={props.isAcmMode ? "Ask an ACM-related question" : "Ask a question"}
            className="flex-1 bg-transparent border-none text-[#141413] dark:text-white placeholder:text-[#73726C] dark:placeholder:text-[#B5B5B5] focus-visible:ring-0 focus-visible:ring-offset-0 focus:outline-none text-sm sm:text-[15.875px] px-0 resize-none min-h-[24px] max-h-[100px] overflow-y-auto scrollbar-thin scrollbar-thumb-[#646362] scrollbar-track-transparent hover:scrollbar-thumb-[#7a7977]"
            style={{
              scrollbarWidth: 'thin',
              scrollbarColor: '#646362 transparent',
            }}
            value={props.input}
            onChange={(e) => {
              // Create a synthetic event that matches the expected type
              const syntheticEvent = {
                ...e,
                target: e.target as any,
                currentTarget: e.currentTarget as any,
              };
              props.handleInputChange(syntheticEvent as any);
            }}
            rows={1}
            onInput={(e) => {
              // Auto-resize textarea as user types
              const target = e.target as HTMLTextAreaElement;
              target.style.height = 'auto';
              const maxHeight = window.innerWidth >= 1024 ? 260 : window.innerWidth >= 768 ? 220 : 150;
              target.style.height = Math.min(target.scrollHeight, maxHeight) + 'px';
            }}
            onKeyDown={(e) => {
              // Submit on Enter, new line on Shift+Enter
              // Disable Enter while streaming — user must click Stop button
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                if (props.isLoading) return;
                const form = e.currentTarget.form;
                if (form) {
                  form.requestSubmit();
                }
              }
            }}
          />
        </div>
        
        {/* Bottom row - ACM Toggle and Send Button */}
        <div className="flex items-center justify-between w-full">
          <div className="flex items-center gap-2">
            {/* ACM Toggle Button */}
            {props.setIsAcmChecked && (
              <button
                type="button"
                onClick={() => props.setIsAcmChecked!(!props.isAcmChecked)}
                className={`
                  flex-shrink-0 px-3 py-1.5 rounded-full font-semibold text-xs transition-all
                  ${props.isAcmChecked 
                    ? 'bg-[#FFC328] text-[#454540]' 
                    : 'bg-transparent border border-[#73726C] dark:border-[#646362] text-[#73726C] dark:text-[#B5B5B5]'
                  }
                `}
              >
                ACMs Only
              </button>
            )}
            
            {/* Placeholder for other icons */}
            <div className="flex items-center gap-1">
              {/* Add other icons here if needed */}
            </div>
          </div>
          
          {/* Send Button - Right side */}
          <div className="flex items-center gap-2">
            {process.env.NEXT_PUBLIC_USE_LLAMACLOUD === "true" &&
              props.setRequestData && (
                <LlamaCloudSelector setRequestData={props.setRequestData} />
              )}
            {props.isLoading ? (
              /* Stop Button when loading */
              <Button 
                type="button"
                onClick={props.stop}
                className="rounded-full bg-[#FFC328] hover:bg-[#FFD155] text-white dark:bg-white dark:hover:bg-gray-100 dark:text-black h-10 w-10 p-0 flex items-center justify-center"
              >
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <rect x="4" y="4" width="8" height="8" fill="currentColor" rx="1"/>
                </svg>
                <span className="sr-only">Stop</span>
              </Button>
            ) : (
              /* Send Button when not loading */
              <Button 
                type="submit" 
                disabled={!props.input.trim()}
                className="rounded-full bg-[#FFC328] hover:bg-[#FFD155] text-white dark:bg-white dark:hover:bg-gray-100 dark:text-black h-10 w-10 p-0 flex items-center justify-center disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <path d="M14 2L7 9M14 2L9.5 14L7 9M14 2L2 6.5L7 9" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
                <span className="sr-only">Send</span>
              </Button>
            )}
          </div>
        </div>
      </div>
    </form>
  );
}
