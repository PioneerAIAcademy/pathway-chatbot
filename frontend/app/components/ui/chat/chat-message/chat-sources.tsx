import { Check, Copy, FileText, ChevronDown } from "lucide-react";
import Image from "next/image";
import { useMemo, useRef, useState, useEffect } from "react";
import { Button } from "../../button";
import { FileIcon } from "../../document-preview";
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "../../hover-card";
import { cn } from "../../lib/utils";
import { useCopyToClipboard } from "../hooks/use-copy-to-clipboard";
import { DocumentFileType, SourceData, SourceNode } from "../index";
import PdfDialog from "../widgets/PdfDialog";

type Document = {
  url: string;
  sources: SourceNode[];
};

export function ChatSources({ data }: { data: SourceData }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const contentRef = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState(0);

  // Create a unique group ID based on first source to scope DOM queries
  const groupId = useMemo(() => {
    if (data.nodes.length > 0) {
      // Use first node's ID as unique identifier for this sources group
      return data.nodes[0].id.replace(/[^a-zA-Z0-9]/g, '').slice(0, 16);
    }
    return '';
  }, [data.nodes]);

  const sortedSources = useMemo(
    () =>
      data.nodes.slice().sort((a, b) => {
        const getNumber = (id: string) =>
          parseInt(id.match(/^\d+/)?.[0] || "0", 10);
        return getNumber(a.citation_node_id) - getNumber(b.citation_node_id);
      }),
    [data.nodes]
  );

  const documents: Document[] = useMemo(() => {
    const nodesByUrl: Record<string, SourceNode[]> = {};
    data.nodes.forEach((node) => {
      const key = node.url;
      nodesByUrl[key] ??= [];
      nodesByUrl[key].push(node);
    });

    return Object.entries(nodesByUrl).map(([url, sources]) => ({
      url,
      sources,
    }));
  }, [data.nodes]);

  // Dynamic height update - only recalculate when expansion state or source count changes
  const sourceCount = data.nodes.length;
  useEffect(() => {
    if (!contentRef.current) return;

    const updateHeight = () => {
      if (isExpanded && contentRef.current) {
        const scrollHeight = contentRef.current.scrollHeight;
        setHeight(scrollHeight);
      } else {
        setHeight(0);
      }
    };

    updateHeight();
    window.addEventListener("resize", updateHeight);
    return () => window.removeEventListener("resize", updateHeight);
  }, [isExpanded, sourceCount]);

  if (documents.length === 0) return null;

  return (
    <div className="mt-4">
      {/* Toggle button */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center gap-2 bg-[#F0EEE6] dark:bg-[rgba(219,219,219,0.08)] border border-[rgba(31,30,29,0.12)] dark:border-[rgba(219,219,219,0.04)] rounded-full px-3 py-2 hover:bg-[#E9E7E1] dark:hover:bg-[rgba(219,219,219,0.12)] transition-colors"
      >
        <div className="flex items-center -space-x-2">
          {sortedSources.slice(0, 3).map((node: SourceNode, index: number) => {
            const domain = new URL(node.url).hostname;
            return (
              <div
                key={index}
                className="w-4 h-4 rounded-full bg-white dark:bg-[#36383a] border border-[rgba(31,30,29,0.12)] dark:border-[#161618] overflow-hidden flex items-center justify-center"
              >
                <Image
                  src={`https://www.google.com/s2/favicons?domain=${domain}&sz=16`}
                  alt={domain}
                  width={16}
                  height={16}
                  className="w-full h-full object-cover"
                />
              </div>
            );
          })}
        </div>
        <span className="text-[#3D3D3A] dark:text-[#FCFCFC] text-[13.781px] leading-[21px] tracking-[-0.1px]">
          {sortedSources.length} {sortedSources.length === 1 ? 'source' : 'sources'}
        </span>
        <ChevronDown
          className={cn(
            "w-4 h-4 text-[#73726C] dark:text-[#B5B5B5] transition-transform duration-300",
            isExpanded && "rotate-180"
          )}
        />
      </button>

      {/* Animated expandable section */}
      <div
        className="overflow-hidden transition-all duration-500 ease-in-out"
        style={{
          height: `${height}px`,
          opacity: isExpanded ? 1 : 0,
          marginTop: isExpanded ? "0.5rem" : "0rem",
        }}
      >
        <div ref={contentRef} className="pt-2 space-y-1">
          {sortedSources.map((node: SourceNode, index: number) => {
            const displayText = (node.metadata?.file_name as string) || node.url;
            
            return (
              <div key={index} className="py-1">
                <a
                  href={node.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  data-citation-group={groupId}
                  data-citation-index={index}
                  className="reference-list-item inline-flex items-start gap-2 text-[13px] sm:text-sm text-[#3D3D3A] dark:text-[#F9F8F6] px-2 py-1 rounded-md group transition-all duration-300"
                >
                  <span className="text-[#E18158] font-medium whitespace-nowrap flex-shrink-0">
                    ^{index + 1}
                  </span>
                  <span className="group-hover:underline break-all">{displayText}</span>
                </a>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// Remaining components
export function SourceInfo({
  node,
  index,
}: {
  node?: SourceNode;
  index: number;
}) {
  if (!node) return <SourceNumberButton index={index} />;
  return (
    <HoverCard>
      <HoverCardTrigger
        className="cursor-default"
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
        }}
      >
        <SourceNumberButton
          index={index}
          className="hover:text-white hover:bg-primary"
        />
      </HoverCardTrigger>
      <HoverCardContent className="w-[400px]">
        <NodeInfo nodeInfo={node} />
      </HoverCardContent>
    </HoverCard>
  );
}

export function SourceNumberButton({
  index,
  className,
  url,
  groupId,
}: {
  index: number;
  className?: string;
  url?: string;
  groupId?: string;
}) {
  const handleMouseEnter = () => {
    if (url && groupId) {
      const refItem = document.querySelector(`.reference-list-item[data-citation-group="${groupId}"][data-citation-index="${index}"]`);
      if (refItem) {
        refItem.classList.add('citation-hovered');
      }
    }
  };

  const handleMouseLeave = () => {
    if (url && groupId) {
      const refItem = document.querySelector(`.reference-list-item[data-citation-group="${groupId}"][data-citation-index="${index}"]`);
      if (refItem) {
        refItem.classList.remove('citation-hovered');
      }
    }
  };

  const badgeContent = (
    <span
      className={cn(
        "inline-flex items-center justify-center font-normal",
        url ? "text-blue-600 dark:text-blue-400 cursor-pointer hover:underline transition-all" : "text-[#C6613F] dark:text-[#E18158]",
        className
      )}
    >
      [{index + 1}]
    </span>
  );

  if (url) {
    return (
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="citation-link no-underline hover:text-blue-800 dark:hover:text-blue-300"
        data-citation-index={index}
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
      >
        {badgeContent}
      </a>
    );
  }

  return badgeContent;
}

function DocumentInfo({ document }: { document: Document }) {
  if (!document.sources.length) return null;
  const { url, sources } = document;
  const fileName = sources[0].metadata.file_name as string | undefined;
  const fileExt = fileName?.split(".").pop();
  const fileImage = fileExt ? FileIcon[fileExt as DocumentFileType] : null;

  const DocumentDetail = (
    <div
      key={url}
      className="h-28 w-48 flex flex-col justify-between p-4 border rounded-md shadow-md cursor-pointer"
    >
      <p
        title={fileName}
        className={cn(
          fileName ? "truncate" : "text-blue-900 break-words",
          "text-left"
        )}
      >
        {fileName ?? url}
      </p>
      <div className="flex justify-between items-center">
        <div className="space-x-2 flex">
          {sources.map((node: SourceNode, index: number) => {
            return (
              <div key={node.id}>
                <SourceInfo node={node} index={index} />
              </div>
            );
          })}
        </div>
        {fileImage ? (
          <div className="relative h-8 w-8 shrink-0 overflow-hidden rounded-md">
            <Image
              className="h-full w-auto"
              priority
              src={fileImage}
              alt="Icon"
            />
          </div>
        ) : (
          <FileText className="text-gray-500" />
        )}
      </div>
    </div>
  );

  if (url.endsWith(".pdf")) {
    return (
      <PdfDialog documentId={url} url={url} trigger={DocumentDetail} />
    );
  }

  return <div onClick={() => window.open(url, "_blank")}>{DocumentDetail}</div>;
}

function NodeInfo({ nodeInfo }: { nodeInfo: SourceNode }) {
  const { isCopied, copyToClipboard } = useCopyToClipboard({ timeout: 1000 });

  const pageNumber =
    (nodeInfo.metadata?.page_number as number) ??
    (nodeInfo.metadata?.page_label as number) ??
    null;

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <span className="font-semibold">
          {pageNumber ? `On page ${pageNumber}:` : "Node content:"}
        </span>
        {nodeInfo.text && (
          <Button
            onClick={(e) => {
              e.stopPropagation();
              copyToClipboard(nodeInfo.text);
            }}
            size="icon"
            variant="ghost"
            className="h-12 w-12 shrink-0"
          >
            {isCopied ? (
              <Check className="h-4 w-4" />
            ) : (
              <Copy className="h-4 w-4" />
            )}
          </Button>
        )}
      </div>

      {nodeInfo.text && (
        <pre className="max-h-[200px] overflow-auto whitespace-pre-line">
          &ldquo;{nodeInfo.text}&rdquo;
        </pre>
      )}
    </div>
  );
}
