import "katex/dist/katex.min.css";
import { FC, memo, useMemo } from "react";
import ReactMarkdown, { Options } from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { ReactNode } from "react";
import { CSSProperties } from "react";

import { DateSpansData, SourceData } from "..";
import { SourceNumberButton } from "./chat-sources";
import { CodeBlock } from "./codeblock";

const MemoizedReactMarkdown: FC<Options> = memo(
  ReactMarkdown,
  (prevProps, nextProps) =>
    prevProps.children === nextProps.children &&
    prevProps.className === nextProps.className,
);

const preprocessLaTeX = (content: string) => {
  // Replace block-level LaTeX delimiters \[ \] with $$ $$
  const blockProcessedContent = content.replace(
    /\\\[([\s\S]*?)\\\]/g,
    (_, equation) => `$$${equation}$$`,
  );
  // Replace inline LaTeX delimiters \( \) with $ $
  const inlineProcessedContent = blockProcessedContent.replace(
    /\\\[([\s\S]*?)\\\]/g,
    (_, equation) => `$${equation}$`,
  );
  return inlineProcessedContent;
};

const preprocessMedia = (content: string) => {
  // Remove `sandbox:` from the beginning of the URL
  // to fix OpenAI's models issue appending `sandbox:` to the relative URL
  return content.replace(/(sandbox|attachment|snt):/g, "");
};

/**
 * Convert [^number] format to [citation:index]() format
 * Maps footnote numbers to sorted source indices
 */
const preprocessFootnoteCitations = (content: string, sources?: SourceData) => {
  if (sources && sources.nodes.length > 0) {
    // Create sorted index mapping: footnote number -> sorted array index
    const sortedSources = sources.nodes.slice().sort((a, b) => {
      const getNumber = (id: string) => parseInt(id.match(/^\d+/)?.[0] || "0", 10);
      return getNumber(a.citation_node_id) - getNumber(b.citation_node_id);
    });
    
    // Match [^1], [^2], etc.
    const footnoteRegex = /\[\^(\d+)\]/g;
    content = content.replace(footnoteRegex, (match, number) => {
      const footnoteNum = parseInt(number, 10);
      // Find the index in sorted array where citation_node_id matches the footnote number
      const sortedIndex = sortedSources.findIndex(node => {
        const nodeNum = parseInt(node.citation_node_id.match(/^\d+/)?.[0] || "0", 10);
        return nodeNum === footnoteNum;
      });
      
      if (sortedIndex >= 0) {
        return `[citation:${sortedIndex}]()`;
      }
      return match; // Keep original if not found
    });
  }
  return content;
};

/**
 * Update the citation flag [citation:id]() to the new format [citation:index](url)
 */
const preprocessCitations = (content: string, sources?: SourceData) => {
  if (sources) {
    const citationRegex = /\[citation:(.+?)\]\(\)/g;
    let match;
    // Find all the citation references in the content
    while ((match = citationRegex.exec(content)) !== null) {
      const citationId = match[1];
      // Check if it's already an index (numeric)
      if (/^\d+$/.test(citationId)) {
        continue; // Already processed by preprocessFootnoteCitations
      }
      // Find the source node with the id equal to the citation-id, also get the index of the source node
      const sourceNode = sources.nodes.find((node) => node.id === citationId);
      // If the source node is found, replace the citation reference with the new format
      if (sourceNode !== undefined) {
        content = content.replace(
          match[0],
          `[citation:${sources.nodes.indexOf(sourceNode)}]()`,
        );
      } else {
        // If the source node is not found, remove the citation reference
        content = content.replace(match[0], "");
      }
    }
  }
  return content;
};

const promoteCalendarSubheaders = (content: string) => {
  return content
    .split("\n")
    .map((line) => {
      const trimmed = line.trim();

      if (trimmed.startsWith("#")) {
        return line;
      }

      if (/^Block\/Term\s+\d+\s*$/i.test(trimmed)) {
        return `### ${trimmed}`;
      }

      return line;
    })
    .join("\n");
};

const preprocessContent = (content: string, sources?: SourceData) => {
  return preprocessCitations(
    preprocessFootnoteCitations(
      promoteCalendarSubheaders(preprocessMedia(preprocessLaTeX(content))),
      sources,
    ),
    sources,
  );
};

const DATE_PATTERN = new RegExp(
  [
    "\\b(?:Mon(?:day)?|Tue(?:s(?:day)?)?|Wed(?:nesday)?|Thu(?:r(?:s(?:day)?)?)?|Fri(?:day)?|Sat(?:urday)?|Sun(?:day)?),?\\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\\s+\\d{1,2}(?:,\\s*\\d{4})?\\b",
    "\\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\\s+\\d{1,2}(?:,\\s*\\d{4})?\\b",
    "\\b(?:\\p{L}+,\\s*)?\\d{1,2}\\s+de\\s+\\p{L}+\\s+de\\s+\\d{4}\\b",
    "\\b(?:\\p{L}+,\\s*)?\\d{1,2}\\s+\\p{L}+\\s+\\d{4}\\b",
    "\\b\\d{1,2}[/-]\\d{1,2}[/-]\\d{2,4}\\b",
    "\\b\\d{4}-\\d{2}-\\d{2}\\b",
  ].join("|"),
  "giu",
);

const DATE_CHIP_CLASSNAME =
  "inline-block align-baseline border rounded-[5px]";

const DATE_CHIP_STYLE: CSSProperties = {
  background: "hsl(var(--chat-bg))",
  color: "hsl(var(--date-chip-text))",
  borderColor: "var(--date-chip-border)",
  borderWidth: "1px",
  borderStyle: "solid",
  borderRadius: "5px",
  padding: "1.5px 6px",
  fontFamily:
    "'Söhne Mono', ui-monospace, 'SFMono-Regular', 'Cascadia Code', monospace",
  fontSize: "15px",
  lineHeight: 1.2,
  letterSpacing: "0.01em",
  fontWeight: 800,
  whiteSpace: "nowrap",
};

const escapeRegExp = (value: string): string => {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
};

const highlightDateText = (text: string): ReactNode[] => {
  const matches = Array.from(text.matchAll(DATE_PATTERN));
  if (matches.length === 0) {
    return [text];
  }

  const parts: ReactNode[] = [];
  let cursor = 0;

  matches.forEach((match, index) => {
    const matched = match[0];
    const start = match.index ?? -1;
    if (!matched || start < cursor) {
      return;
    }

    if (start > cursor) {
      parts.push(text.slice(cursor, start));
    }

    parts.push(
      <span
        key={`date-${start}-${index}`}
        className={DATE_CHIP_CLASSNAME}
        style={DATE_CHIP_STYLE}
      >
        {matched}
      </span>,
    );
    cursor = start + matched.length;
  });

  if (cursor < text.length) {
    parts.push(text.slice(cursor));
  }

  return parts;
};

const highlightDatePhrases = (text: string, phrases: string[]): ReactNode[] => {
  if (!text || phrases.length === 0) {
    return [text];
  }

  const escaped = phrases
    .map((phrase) => phrase.trim())
    .filter((phrase) => phrase.length > 0)
    .sort((a, b) => b.length - a.length)
    .map(escapeRegExp);

  if (escaped.length === 0) {
    return [text];
  }

  const phraseRegex = new RegExp(`(${escaped.join("|")})`, "giu");
  const segments = text.split(phraseRegex);
  const normalizedPhraseSet = new Set(
    phrases.map((phrase) => phrase.trim().toLocaleLowerCase()),
  );

  return segments
    .filter((segment) => segment.length > 0)
    .map((segment, index) => {
      const isDate = normalizedPhraseSet.has(segment.trim().toLocaleLowerCase());
      if (!isDate) {
        return <span key={`date-text-${index}`}>{segment}</span>;
      }

      return (
        <span
          key={`date-phrase-${index}`}
          className={DATE_CHIP_CLASSNAME}
          style={DATE_CHIP_STYLE}
        >
          {segment}
        </span>
      );
    });
};

const highlightDatesInChildren = (
  children: ReactNode,
  phrases: string[],
): ReactNode => {
  if (typeof children === "string") {
    return phrases.length > 0
      ? highlightDatePhrases(children, phrases)
      : highlightDateText(children);
  }

  if (Array.isArray(children)) {
    return children.map((child, index) => {
      if (typeof child === "string") {
        return (
          <span key={`date-text-${index}`}>
            {phrases.length > 0
              ? highlightDatePhrases(child, phrases)
              : highlightDateText(child)}
          </span>
        );
      }
      return child;
    });
  }

  return children;
};

export default function Markdown({
  content,
  sources,
  dateSpans,
}: {
  content: string;
  sources?: SourceData;
  dateSpans?: DateSpansData;
}) {
  const processedContent = preprocessContent(content, sources);
  const normalizedDatePhrases = useMemo(() => {
    if (!dateSpans?.phrases?.length) {
      return [] as string[];
    }

    const seen = new Set<string>();
    const uniquePhrases: string[] = [];
    for (const phrase of dateSpans.phrases) {
      const value = (phrase || "").trim();
      if (!value) {
        continue;
      }
      const key = value.toLowerCase();
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      uniquePhrases.push(value);
    }

    return uniquePhrases;
  }, [dateSpans?.phrases]);

  // Create sorted sources array to match chat-sources.tsx display order
  const sortedSources = useMemo(() => 
    sources?.nodes.slice().sort((a, b) => {
      const getNumber = (id: string) => parseInt(id.match(/^\d+/)?.[0] || "0", 10);
      return getNumber(a.citation_node_id) - getNumber(b.citation_node_id);
    }),
    [sources?.nodes]
  );

  // Create unique group ID to scope DOM queries (must match chat-sources.tsx)
  const groupId = useMemo(() => {
    if (sources?.nodes && sources.nodes.length > 0) {
      return sources.nodes[0].id.replace(/[^a-zA-Z0-9]/g, '').slice(0, 16);
    }
    return '';
  }, [sources?.nodes]);

  return (
    <MemoizedReactMarkdown
      className="prose dark:prose-invert prose-p:leading-relaxed prose-pre:p-0 break-words overflow-wrap-anywhere custom-markdown text-[#3D3D3A] dark:text-[#F9F8F6] text-sm sm:text-[15.75px] leading-[24px] sm:leading-[28px] tracking-[-0.1px] max-w-full"
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[rehypeKatex as any]}
      components={{
        p({ children }) {
          return (
            <p className="mb-2 last:mb-0">
              {highlightDatesInChildren(children, normalizedDatePhrases)}
            </p>
          );
        },
        h2({ children }) {
          return (
            <h2 className="mt-5 mb-2 text-[22px] sm:text-[24px] leading-[1.2] font-semibold tracking-[-0.2px]">
              {highlightDatesInChildren(children, normalizedDatePhrases)}
            </h2>
          );
        },
        h3({ children }) {
          return (
            <h3 className="mt-4 mb-2 text-[20px] sm:text-[22px] leading-[1.25] font-semibold tracking-[-0.2px]">
              {highlightDatesInChildren(children, normalizedDatePhrases)}
            </h3>
          );
        },
        li({ children }) {
          return <li>{highlightDatesInChildren(children, normalizedDatePhrases)}</li>;
        },
        code({ node, inline, className, children, ...props }) {
          if (children.length) {
            if (children[0] == "▍") {
              return (
                <span className="mt-1 animate-pulse cursor-default">▍</span>
              );
            }

            children[0] = (children[0] as string).replace("`▍`", "▍");
          }

          const match = /language-(\w+)/.exec(className || "");

          if (inline) {
            return (
              <code className={className} {...props}>
                {children}
              </code>
            );
          }

          return (
            <CodeBlock
              key={Math.random()}
              language={(match && match[1]) || ""}
              value={String(children).replace(/\n$/, "")}
              {...props}
            />
          );
        },
        a({ href, children }) {
          // If a text link starts with 'citation:', then render it as a citation reference
          if (
            Array.isArray(children) &&
            typeof children[0] === "string" &&
            children[0].startsWith("citation:")
          ) {
            const index = Number(children[0].replace("citation:", ""));
            if (!isNaN(index) && sortedSources && sortedSources[index]) {
              const sourceUrl = sortedSources[index].url;
              return <SourceNumberButton index={index} url={sourceUrl} groupId={groupId} />;
            } else {
              // citation is not looked up yet, don't render anything
              return <></>;
            }
          }
          return (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
            >
              {children}
            </a>
          );
        },
      }}
    >
      {processedContent}
    </MemoizedReactMarkdown>
  );
}
