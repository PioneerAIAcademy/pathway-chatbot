import { JSONValue } from "ai";
import { isValidUrl } from "../lib/utils";
import ChatInput from "./chat-input";
import ChatMessages from "./chat-messages";

export { type ChatHandler } from "./chat.interface";
export { ChatInput, ChatMessages };

export enum MessageAnnotationType {
  IMAGE = "image",
  DOCUMENT_FILE = "document_file",
  SOURCES = "sources",
  EVENTS = "events",
  TOOLS = "tools",
  CALENDAR = "calendar",
  CALENDAR_SKELETON = "calendar_skeleton",
  CALENDAR_HEADER = "calendar_header",
  CALENDAR_SPOTLIGHT = "calendar_spotlight",
  CALENDAR_TIMELINE = "calendar_timeline",
  CALENDAR_FOOTER = "calendar_footer",
  CALENDAR_ERROR = "calendar_error",
  DATE_SPANS = "date_spans",
  SUGGESTED_QUESTIONS = "suggested_questions",
  LANGFUSE_TRACE_ID = "langfuse_trace_id",
  USER_LANGUAGE = "user_language",
}

export type ImageData = {
  url: string;
};

export type DocumentFileType = "csv" | "pdf" | "txt" | "docx";

export type DocumentFileContent = {
  type: "ref" | "text";
  value: string[] | string;
};

export type DocumentFile = {
  id: string;
  filename: string;
  filesize: number;
  filetype: DocumentFileType;
  content: DocumentFileContent;
};

export type DocumentFileData = {
  files: DocumentFile[];
};

export type SourceNode = {
  id: string;
  citation_node_id: string;
  metadata: Record<string, unknown>;
  score?: number;
  text: string;
  url: string;
};

export type SourceData = {
  nodes: SourceNode[];
};

export type EventData = {
  title: string;
  isCollapsed: boolean;
};

export type ToolData = {
  toolCall: {
    id: string;
    name: string;
    input: {
      [key: string]: JSONValue;
    };
  };
  toolOutput: {
    output: JSONValue;
    isError: boolean;
  };
};

export type CalendarEvent = {
  date: string;
  name: string;
  description?: string;
  status: "past" | "today" | "soon" | "upcoming";
  countdown?: string;
  section?: string;
};

export type CalendarCardData = {
  type: "block" | "semester" | "deadline" | "graduation";
  title: string;
  subtitle: string;
  status: "active" | "upcoming" | "past";
  spotlight?: {
    urgency: "urgent" | "warning" | "info" | "calm";
    date: string;
    title: string;
    description: string;
    countdown: string;
  };
  events: CalendarEvent[];
  tabs?: { label: string; active: boolean; events?: CalendarEvent[] }[];
  sourceUrl: string;
  suggestedQuestions: string[];
  footnote?: string;
  textFormatOffer?: string;
};

export type CalendarCardPhase =
  | "skeleton"
  | "header"
  | "spotlight"
  | "timeline"
  | "footer"
  | "complete";

export type CalendarCardState = {
  phase: CalendarCardPhase;
  type?: CalendarCardData["type"];
  title?: string;
  subtitle?: string;
  status?: CalendarCardData["status"];
  spotlight?: CalendarCardData["spotlight"];
  events?: CalendarEvent[];
  tabs?: CalendarCardData["tabs"];
  sourceUrl?: string;
  suggestedQuestions?: string[];
  footnote?: string;
  textFormatOffer?: string;
};

export type SuggestedQuestionsData = string[];

export type UserLanguageData = {
  language: string;
};

export type DateSpansData = {
  phrases: string[];
  language?: string;
};

export type AnnotationData =
  | ImageData
  | DocumentFileData
  | SourceData
  | EventData
  | ToolData
  | CalendarCardData
  | DateSpansData
  | SuggestedQuestionsData
  | UserLanguageData;

export type MessageAnnotation = {
  type: MessageAnnotationType;
  data: AnnotationData;
  trace_id?: string;
};

const NODE_SCORE_THRESHOLD = 0.25;

export function getLangfuseTraceId(
  annotations: MessageAnnotation[],
  type: MessageAnnotationType
): any {
  return annotations.find((annotation) => annotation.type === type);
}

export function getAnnotationData<T>(
  annotations: MessageAnnotation[],
  type: MessageAnnotationType,
): T[] {
  return annotations.filter((a) => a.type === type).map((a) => a.data as T);
}

export function getSourceAnnotationData(
  annotations: MessageAnnotation[],
): SourceData[] {
  const data = getAnnotationData<SourceData>(
    annotations,
    MessageAnnotationType.SOURCES,
  );
  if (data.length > 0) {
    const sourceData = data[0] as SourceData;
    if (sourceData.nodes) {
      sourceData.nodes = preprocessSourceNodes(sourceData.nodes);
    }
  }
  return data;
}

function preprocessSourceNodes(nodes: SourceNode[]): SourceNode[] {
  // Filter source nodes has lower score
  nodes = nodes
    // .filter((node) => (node.score ?? 1) > NODE_SCORE_THRESHOLD)
    .filter((node) => isValidUrl(node.url))
    .sort((a, b) => (b.score ?? 1) - (a.score ?? 1))
    .map((node) => {
      // remove trailing slash for node url if exists
      node.url = node.url.replace(/\/$/, "");
      return node;
    });
  return nodes;
}
