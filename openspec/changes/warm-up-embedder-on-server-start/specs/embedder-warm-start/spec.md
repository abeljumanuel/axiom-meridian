## ADDED Requirements

### Requirement: The server begins loading the embedding model as soon as it starts
Both `run_stdio` and `run_http` SHALL start loading the embedding model in a background thread immediately after database initialization, without this delaying the server's readiness to accept connections or serve non-embedding tool calls.

#### Scenario: Server start is not delayed by the model load
- **WHEN** the MCP server starts via `run_stdio` or `run_http`
- **THEN** it begins accepting connections without waiting for the embedding model to finish loading

#### Scenario: A real embedding request arrives while warm-up is in progress
- **WHEN** `approve_proposal` or a semantic (`query_text`) search triggers `embedder.generate_embedding`/`generate_embeddings_batch` while the background warm-up thread is still loading the model
- **THEN** the request waits only for that same in-progress load to finish — it does not trigger a second, redundant load

#### Scenario: A real embedding request arrives after warm-up has finished
- **WHEN** `approve_proposal` or a semantic search runs after the background warm-up thread has already finished loading the model
- **THEN** the request completes at the already-warm latency (no reload)
