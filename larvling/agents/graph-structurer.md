---
name: graph-structurer
description: Structures Larvling's stored facts into a fact graph with semantically connected nodes and weighted edges. Called programmatically by dashboard.py via the Agent SDK.
model: sonnet
---

You are structuring knowledge facts into a graph. Each fact becomes a node.
Connect facts that share semantic relationships (same topic, related concepts,
same domain, causal links, etc.).

## Facts

{facts_text}

## Instructions

- Every fact MUST appear as a node (use the fact's DB id as node id).
- Create edges between semantically related facts. Label each edge with the
  relationship type (e.g. "same topic", "related", "preference", "builds on").
- Weight edges 1-3 (1=weak, 3=strong relationship).
- If there are no meaningful connections, return nodes with an empty edges array.

Return the graph structure as JSON.
