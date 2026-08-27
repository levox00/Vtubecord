# Memory Architecture

## Memory Types

| Type          | Purpose                              | Example |
|---------------|--------------------------------------|---------|
| short_term    | Current conversation window          | Last N messages |
| episodic      | Specific experiences                 | "Played Minecraft on 2026-08-17..." |
| semantic      | Facts about the world / user         | "User dislikes horror games" |
| relationship  | Per-user relationship state          | trust, familiarity, inside jokes |
| skill         | Learned capabilities                 | Minecraft combat: 0.58 |
| experience    | Game sessions & significant events   | Survive first night — Success |

## Memory Record Schema (Conceptual)

```python
id: UUID
type: MemoryType
content: str | dict
importance: float          # 0.0 – 1.0
confidence: float
created_at: datetime
last_accessed: datetime
access_count: int
source: str                # conversation_id, game_session, reflection, ...
related_entities: list     # user_ids, game names, etc.
embedding: vector | null
pinned: bool
metadata: dict
```

## Retrieval Strategy

Never dump the entire database into the LLM.

```
Current context
+ Top-k relevant memories (embedding similarity × importance × recency)
+ Recent episodic memories
+ Active relationship state
+ Current goals
+ Current emotional state
→ Prompt
```

## Consolidation Pipeline

```
Conversation ends
    ↓
MemoryExtractor (LLM or rules + LLM)
    ↓
Candidate memories
    ↓
Importance scoring
    ↓
Deduplication
    ↓
Conflict detection
    ↓
Store / Update / Flag for review
```

Conflict example:
- Existing: "User hates horror games" (confidence 0.95)
- New: "User loves horror games now"
→ Create conflict record or update with lower confidence + history, never silent overwrite.

## Decay

Unimportant, rarely accessed memories gradually lose retrieval probability.  
Pinned and high-importance memories persist.

## Implementation Notes (Phase 3)

- SQLite: store embeddings as JSON / blob + simple cosine in Python
- PostgreSQL: use pgvector with HNSW or IVFFlat index
- Embedding model: start with a small local model or hosted embedding API; keep it swappable.