# Article Pipeline

From keywords to WordPress posts — research, write, review, revise, publish.

## Architecture

```
keyword → [Research] → [Outline] → [Write] → [Self-Review] → (Human Review)
                                    ↑                              │
                                    └── Revise ← Feedback ←────────┘
                                                              │
                                                         Approve → [Publish]
```

## Modules

| Module | File | Role |
|--------|------|------|
| DB | `db.py` | SQLite task queue, version tracking, feedback log |
| Research | `research.py` | cocobook MCP + DDG web + code grep + VM consult |
| Outline | `outline.py` | Structured outline via GLM-5.1 (Ollama fallback) |
| Writer | `writer.py` | Article generation + human-feedback revision + terminology post-processing |
| Review | `review.py` | 6-dimension scoring: AI detection, fabrication, word count, format, semantic facts, terminology |
| Pipeline | `pipeline.py` | Orchestrates stages, retry logic |
| Publish | `publish.py` | WordPress REST API (Gutenberg blocks) + translate bridge fallback |
| Server | `review_server.py` | Web UI: review queue, version history, revision workflow, batch operations |

## Quick Start

```bash
# Install
pip install -e .

# Configure
cp ~/.config/article-pipeline/config.yaml.example
# Set env vars: ANTHROPIC_API_KEY, AP_WP_USERNAME, AP_WP_APP_PASSWORD

# Add keywords
article-pipeline add --keyword "WordPress 性能优化" --category wp-tech

# Run pipeline  
article-pipeline run --limit 5

# Review
article-pipeline review-server  # → http://localhost:8765
```

## Review Flow

1. Pipeline produces draft → auto-scored on 6 dimensions
2. Human reviews at `http://localhost:8765`
3. "Request Revision" → write specific feedback → AI revises → new version
4. Version history tracks score changes across revisions
5. Approve → publishes to WordPress with Gutenberg block format

## API

### CLI

```
article-pipeline add --keyword "..." --category wp-tech|book-knowledge
article-pipeline list [--status queued|reviewing|done]
article-pipeline run [--limit 5]
article-pipeline continue <task_id>
article-pipeline review-server
article-pipeline publish <task_id>
article-pipeline skip <task_id> --reason "..."
```

### Review Server Endpoints

| Path | Method | Action |
|------|--------|--------|
| `/` | GET | Review queue with stats, filter, sort |
| `/view?id=` | GET | Article detail + scores + version history |
| `/approve?id=` | POST | Approve and publish |
| `/revision?id=` | GET | Revision form with issues checklist |
| `/submit-revision?id=` | POST | Submit feedback → AI revise → new version |
| `/auto-revise?id=` | POST | Auto-revise from detection suggestions |
| `/batch-approve?ids=` | GET | Batch approve |
| `/reject?id=` | POST | Reject with reason |

## Scoring Dimensions

| Dimension | What it checks |
|-----------|---------------|
| AI Detection | 40+ patterns (clichés, fillers, connectors, translation-ese, AI compounds) |
| Fabrication | Fake URLs, bare domain citations, invented sources |
| Semantic Facts | Claim verification against research notes |
| Terminology | WP Chinese glossary enforcement (区块 not 块) |
| Format | H2/H3 structure, paragraph count |
| Word Count | Tier thresholds (A: 1500-4000, B: 3000-8000) |

## Dependencies

- Python 3.11+
- GLM-5.1 via z.ai API (Anthropic-compatible endpoint)
- cocobook MCP (kk-pc:8086) for research annotations
- WordPress REST API for publishing
- translate VM for Gutenberg conversion and bridge publishing

## Dev

```bash
pip install -e ".[test]"
pytest tests/ -v
```
