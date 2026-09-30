# warm-up-embedder-on-server-start

the lazy-loaded sentence-transformers model pays its multi-second import+instantiation cost inline on whichever call happens to trigger it first — now every approve_proposal, not just the first semantic query — risking an MCP client's connection/call timeout
