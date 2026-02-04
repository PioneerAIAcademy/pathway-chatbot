import "katex/dist/katex.min.css";
import { FC, memo, useMemo } from "react";
import ReactMarkdown, { Options } from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import { SourceData } from "..";
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

const preprocessContent = (content: string, sources?: SourceData) => {
  return preprocessCitations(
    preprocessFootnoteCitations(
      preprocessMedia(preprocessLaTeX(content)),
      sources,
    ),
    sources,
  );
};

export default function Markdown({
  content,
  sources,
}: {
  content: string;
  sources?: SourceData;
}) {
  const processedContent = preprocessContent(content, sources);

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
          return <p className="mb-2 last:mb-0">{children}</p>;
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
          return <a href={href}>{children}</a>;
        },
      }}
    >
      {processedContent}
    </MemoizedReactMarkdown>
  );
}
