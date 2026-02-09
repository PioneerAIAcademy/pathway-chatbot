import time
import asyncio
import logging
from typing import Any, List, Optional, Tuple, Dict
from collections import defaultdict
from llama_index.core.chat_engine import CondensePlusContextChatEngine
from llama_index.core.indices.query.schema import QueryBundle
from llama_index.core.schema import MetadataMode, NodeWithScore
from llama_index.core.base.llms.types import ChatMessage, MessageRole
from llama_index.core.callbacks import CallbackManager, trace_method
from llama_index.core.callbacks.schema import CBEventType, EventPayload
from llama_index.core.types import Thread

import voyageai
vo = voyageai.Client()  # This will automatically use the environment variable VOYAGE_API_KEY.


from app.engine.custom_node_with_score import CustomNodeWithScore

from llama_index.core.chat_engine.types import (
    AgentChatResponse,
    BaseChatEngine,
    StreamingAgentChatResponse,
    ToolOutput,
)


logger = logging.getLogger(__name__)

class CustomCondensePlusContextChatEngine(CondensePlusContextChatEngine):
    
    def _retrieve_context(self, message: str) -> Tuple[str, List[NodeWithScore]]:
        """Build context for a message from retriever."""
        nodes = self._retriever.retrieve(message)
        for i, node in enumerate(nodes):
            print(f"Node {i+1}: {node.text}\n\n\n")
        for postprocessor in self._node_postprocessors:
            nodes = postprocessor.postprocess_nodes(
                nodes, query_bundle=QueryBundle(message)
            )
            for i, node in enumerate(nodes):
                print(f"Node {i+1}: {node.text}\n\n\n")
        
        # print(nodes)

        # **Organize nodes using the earlier functions**
        organized_nodes = self._organize_nodes(nodes, message=message)
        # print(len(organized_nodes))
        # print(organized_nodes)

        # Custom formatting of context_str
        context_str = "We have {} nodes:\n".format(len(organized_nodes))
        
        nodes_with_citation_node_id = []
        
        for i, node_with_score in enumerate(organized_nodes, start=1):
            node_text = node_with_score.node.get_text()
            context_str += f'node_id: {i}\ntext: {node_text}\n\n'

            # Create a new node with citation_node_id
            new_node = CustomNodeWithScore(node=node_with_score.node, score=node_with_score.score)

            # Assign citation_node_id to the new node
            new_node.citation_node_id = str(i)
            nodes_with_citation_node_id.append(new_node)
            
        return context_str, nodes_with_citation_node_id

    async def _aretrieve_context(self, message: str) -> Tuple[str, List[CustomNodeWithScore]]:
        """Build context for a message from retriever asynchronously."""
        nodes = await self._retriever.aretrieve(message)
        for postprocessor in self._node_postprocessors:
            nodes = postprocessor.postprocess_nodes(
                nodes, query_bundle=QueryBundle(message)
            )
        
        # print(len(nodes))
        # print(nodes)
        # **Organize nodes using the earlier functions**
        organized_nodes = self._organize_nodes(nodes, message=message)
        # print(len(organized_nodes))
        # for node in organized_nodes:
        #     print(node.text)
        #     print(node.metadata["url"])

        # Custom formatting of context_str
        context_str = "We have {} nodes:\n".format(len(organized_nodes))
        
        nodes_with_citation_node_id = []
        
        for i, node_with_score in enumerate(organized_nodes, start=1):
            node_text = node_with_score.node.get_text()
            context_str += f'node_id: {i}\ntext: {node_text}\n\n'

            # Create a new node with citation_node_id
            new_node = CustomNodeWithScore(node=node_with_score.node, score=node_with_score.score)

            # Assign citation_node_id to the new node
            new_node.citation_node_id = str(i)
            nodes_with_citation_node_id.append(new_node)

        return context_str, nodes_with_citation_node_id

    def _organize_nodes(self, nodes: List[NodeWithScore], message: str = "") -> List[NodeWithScore]:
        """Organize nodes by URL, sequence, and merge overlapping nodes."""
        rerank_model = "rerank-lite-1"
        rerank_threshold = 0.21
        rerank_k = 17
        rerank = True
        
        #retrieved_threshold filter is ignored because it's value is 0

        # CHANGED - use node context metadata for text to send to llm
        node_texts_ordered = [node.text for node in nodes]

        # CHANGED - dedup node texts
        node_texts = list(set(node_texts_ordered))

        if rerank and len(node_texts) > 1:
            callback_manager = getattr(self, "callback_manager", None) or getattr(self, "_callback_manager", None)
            event_id = None
            if callback_manager is not None:
                event_id = callback_manager.on_event_start(
                    CBEventType.RERANKING,
                    payload={
                        EventPayload.QUERY_STR: message,
                        EventPayload.TOP_K: rerank_k,
                        EventPayload.MODEL_NAME: rerank_model,
                    },
                )

            success = False
            retries = 0
            last_exc: Exception | None = None
            while not success and retries < 3:
                try:
                    reranking = vo.rerank(message, node_texts, model=rerank_model, top_k=rerank_k)
                    node_texts = [r.document for r in reranking.results if r.relevance_score >= rerank_threshold]
                    # print(f"---\n{node_texts}\n---\n\n")
                    success = True
                except Exception as exc:
                    last_exc = exc
                    time.sleep(5) # originally 60
                    retries += 1

            if callback_manager is not None:
                end_payload: dict[str, Any] = {"rerank_success": success}
                if not success and last_exc is not None:
                    end_payload[EventPayload.EXCEPTION] = repr(last_exc)
                callback_manager.on_event_end(
                    CBEventType.RERANKING,
                    payload=end_payload,
                    event_id=event_id or "",
                )

        nodes_ranked = []
        if len(node_texts) == 0:
            node_texts = ['qwer asdf']
        else:
            # CHANGED - get filtered and reranked nodes
            nodes_ranked = [nodes[node_texts_ordered.index(node_text)] for node_text in node_texts]
            # for node_text in node_texts:
            #     node_text_nodes.append((node_text, nodes[node_texts_ordered.index(node_text)]))

        # Step 5: Group nodes by page (URL)
        pages = defaultdict(list)
        for node_with_score in nodes_ranked:
            node = node_with_score.node
            url = node.metadata.get('url', 'unknown_url')
            pages[url].append(node_with_score)
                
        # Step 6: Order nodes on each page by sequence number
        for url, page_nodes in pages.items():
            pages[url] = sorted(page_nodes, key=lambda x: x.node.metadata.get('sequence', 0))

        # Step 7: Merge overlapping nodes with the same headers
        organized_nodes = []
        for url, page_nodes in pages.items():
            merged_nodes = self._merge_nodes_with_headers(page_nodes)
            organized_nodes.extend(merged_nodes)
        
        return organized_nodes

    def _merge_nodes_with_headers(self, nodes: List[NodeWithScore]) -> List[NodeWithScore]:
        """Merge nodes while preserving complete phrases and context."""
        if not nodes:
            return []

        # Use the metadata from the first node
        merged_node_with_score = nodes[0]
        
        # Instead of merging word by word, let's work with complete phrases
        all_texts = [node.node.get_text() for node in nodes] # get all texts
        
        # Create a scoring system for each complete text
        text_scores = []
        for idx, text in enumerate(all_texts):
            score = nodes[idx].score
            sequence = nodes[idx].node.metadata.get('sequence', 0)
            text_scores.append((text, score, sequence)) # add tuple of text and score
        
        # Sort texts by score in ascendent order
        text_scores.sort(key=lambda x: x[2]) # sort by sequence
        
        # Initialize with the first text
        final_text = text_scores[0][0]

        # Concatenate subsequent texts
        for text, _, _ in text_scores[1:]:
            if text.strip():  # Check if text is not empty
                if final_text.strip():  # If final_text is not empty, add double newline
                    final_text += '\n\n'
                final_text += text.strip()
        
        
        # # Function to check if a phrase is semantically different enough to keep
        # def is_unique_content(existing_text: str, new_text: str) -> bool:
        #     existing_words = set(existing_text.lower().split())
        #     new_words = set(new_text.lower().split())
            
        #     # Calculate word overlap
        #     overlap = len(existing_words.intersection(new_words))
        #     total_words = len(new_words)
            
        #     # If less than 70% overlap, consider it unique content
        #     return (overlap / total_words) < 0.7 if total_words > 0 else False
        
        # # Add unique content from other texts
        # for text, _ in text_scores[1:]:
        #     if is_unique_content(final_text, text):
        #         # Add a separator if needed
        #         if not final_text.endswith('.') and not final_text.endswith('?'):
        #             final_text += '. '
        #         else:
        #             final_text += ' '
        #         final_text += text
        
        # Calculate average score
        total_score = sum(node.score for node in nodes)
        average_score = total_score / len(nodes)
        
        # Update the merged node
        merged_node_with_score.node.text = final_text
        merged_node_with_score.score = average_score
        
        return [merged_node_with_score]


    def _split_header_content(self, text: str) -> Tuple[str, str]:
        """Split the text into header and content."""
        lines = text.split('\n', 1)
        if len(lines) > 1:
            return lines[0] + '\n', lines[1]
        return '', text

    def _merge_content(self, existing: str, new: str) -> str:
        """Merge two content strings, removing duplicate words."""
        combined = existing + ' ' + new
        words = combined.split()
        return ' '.join(sorted(set(words), key=words.index))
    
    def reset(self) -> None:
        # Clear chat history
        self._memory.reset()
        self.chat_history.clear()
        
    def get_chat_history(self) -> List[ChatMessage]:
        return self.chat_history