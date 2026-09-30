# fix-approve-proposal-stale-embeddings

approve_proposal never embeds newly-created rows nor refreshes ChromaDB after an update, so semantic search (query_text) silently omits new rules/lessons and serves stale text/tags for updated ones
