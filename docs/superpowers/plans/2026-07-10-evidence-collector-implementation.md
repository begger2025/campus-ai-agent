# 联网证据采集 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an isolated, administrator-reviewed AI web-evidence collector for Sun Yat-sen University that imports only approved, traceable evidence into the existing `raw_posts` pipeline.

**Architecture:** A new root-level `evidence_collector/` FastAPI service owns `evidence_*` tables and all provider/search, scope, verification, review, and delivery state. The existing FastAPI backend remains the browser-facing authenticated boundary: it proxies administrator actions to the collector and is the only component allowed to create or reuse `RawPost` rows after approval. `MediaCrawler/` remains untouched.

**Tech Stack:** Python 3, FastAPI, Pydantic, SQLAlchemy, PyMySQL/MySQL, SQLite test database, `requests`, Vue 3, Element Plus, Vite, `unittest`.

---

## File structure locked by this plan

```text
evidence_collector/
├─ __init__.py
├─ config.py                 # Environment-only settings and enabled provider definitions
├─ database.py               # Collector-owned SQLAlchemy engine, Base and session dependency
├─ models.py                 # evidence_* tables only
├─ schemas.py                # Pydantic request/response contracts
├─ main.py                   # Collector FastAPI app and internal router registration
├─ services/
│  ├─ canonicalize.py        # URL normalization and stable SHA-256 identifiers
│  ├─ scope_policy.py        # Pure SYSU/source/evidence admission rules
│  ├─ providers.py           # Provider contract, registry and disabled-safe adapters
│  ├─ collection.py          # Run/query/document/item orchestration
│  ├─ verification.py        # Rule + model-verifier decision merge
│  └─ delivery.py            # Approved-item payload and delivery acknowledgement
└─ tests/
   ├─ test_database_models.py
   ├─ test_scope_policy.py
   ├─ test_providers.py
   ├─ test_collection.py
   ├─ test_internal_api.py
   └─ test_delivery.py

backend/
├─ routers/admin_evidence.py
├─ services/evidence_collector_client.py
├─ services/evidence_import_service.py
└─ tests/test_admin_evidence.py
   tests/test_evidence_import.py

frontend/src/
├─ api/admin.js              # Extend the established administrator API module
├─ router/index.js           # Add the admin-only route
└─ views/AdminEvidenceView.vue

scripts/init_evidence_db.py  # Idempotent collector-table initializer
docs/evidence-collector-runbook.md
```

### Task 1: Create the isolated collector foundation and safe configuration

**Files:**
- Create: `evidence_collector/__init__.py`
- Create: `evidence_collector/config.py`
- Create: `evidence_collector/database.py`
- Create: `evidence_collector/tests/__init__.py`
- Modify: `.env.example`
- Modify: `.gitignore`
- Test: `evidence_collector/tests/test_database_models.py`

- [ ] **Step 1: Write the failing settings test**

```python
# evidence_collector/tests/test_database_models.py
import os
import unittest
from unittest.mock import patch


class CollectorSettingsTest(unittest.TestCase):
    def test_missing_provider_keys_leave_all_providers_disabled(self):
        with patch.dict(os.environ, {"EVIDENCE_COLLECTOR_TOKEN": "test-token"}, clear=True):
            from evidence_collector.config import get_settings
            settings = get_settings.cache_clear() or get_settings()
            self.assertEqual(settings.enabled_provider_ids, ())
            self.assertEqual(settings.collector_token, "test-token")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/Scripts/python.exe -m unittest evidence_collector.tests.test_database_models.CollectorSettingsTest -v`

Expected: `ModuleNotFoundError: No module named 'evidence_collector'`.

- [ ] **Step 3: Add environment-only settings**

```python
# evidence_collector/config.py
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class ProviderSettings:
    provider_id: str
    model: str
    api_key: str
    base_url: str
    web_search_enabled: bool


@dataclass(frozen=True)
class Settings:
    database_url: str
    collector_token: str
    enabled_provider_ids: tuple[str, ...]
    providers: dict[str, ProviderSettings]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    providers = {}
    for provider_id in ("deepseek", "glm", "kimi", "doubao", "qwen"):
        prefix = f"EVIDENCE_{provider_id.upper()}"
        api_key = os.getenv(f"{prefix}_API_KEY", "").strip()
        enabled = os.getenv(f"{prefix}_WEB_SEARCH_ENABLED", "false").lower() == "true"
        if api_key and enabled:
            providers[provider_id] = ProviderSettings(
                provider_id=provider_id,
                model=os.getenv(f"{prefix}_MODEL", "").strip(),
                api_key=api_key,
                base_url=os.getenv(f"{prefix}_BASE_URL", "").strip(),
                web_search_enabled=True,
            )
    return Settings(
        database_url=os.getenv("EVIDENCE_DATABASE_URL") or os.getenv("DATABASE_URL", "sqlite:///data/campus.db"),
        collector_token=os.getenv("EVIDENCE_COLLECTOR_TOKEN", "").strip(),
        enabled_provider_ids=tuple(sorted(providers)),
        providers=providers,
    )
```

Add named-but-empty keys to `.env.example`, never values: `EVIDENCE_COLLECTOR_TOKEN`, `EVIDENCE_DATABASE_URL`, and the five `EVIDENCE_<PROVIDER>_{API_KEY,MODEL,BASE_URL,WEB_SEARCH_ENABLED}` groups. Add `evidence_collector/.env` and `evidence_collector/data/` to `.gitignore`.

- [ ] **Step 4: Add the dedicated database module**

```python
# evidence_collector/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from evidence_collector.config import get_settings


class Base(DeclarativeBase):
    pass


def build_session_factory(database_url: str | None = None):
    url = database_url or get_settings().database_url
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {"pool_pre_ping": True, "pool_recycle": 3600}
    return sessionmaker(autocommit=False, autoflush=False, bind=create_engine(url, **kwargs))
```

- [ ] **Step 5: Run the settings test to verify it passes**

Run: `./.venv/Scripts/python.exe -m unittest evidence_collector.tests.test_database_models.CollectorSettingsTest -v`

Expected: `OK`.

- [ ] **Step 6: Commit the foundation**

```bash
git add evidence_collector .env.example .gitignore
git commit -m "feat(evidence): add collector configuration foundation"
```

### Task 2: Add collector-owned evidence tables and idempotent initialization

**Files:**
- Create: `evidence_collector/models.py`
- Create: `scripts/init_evidence_db.py`
- Modify: `evidence_collector/database.py`
- Modify: `evidence_collector/tests/test_database_models.py`

- [ ] **Step 1: Write a failing model/constraint test**

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from evidence_collector.database import Base
from evidence_collector.models import EvidenceDocument, EvidenceRun


def make_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_canonical_url_is_unique_per_source_type():
    db = make_db()
    run = EvidenceRun(topic="中山大学食堂", status="created")
    db.add(run)
    db.flush()
    db.add_all([
        EvidenceDocument(run_id=run.id, source_type="official_notice", canonical_url="https://www.sysu.edu.cn/a", title="A", evidence_quote="中山大学公告"),
        EvidenceDocument(run_id=run.id, source_type="official_notice", canonical_url="https://www.sysu.edu.cn/a", title="B", evidence_quote="中山大学公告"),
    ])
    with __import__("unittest").TestCase().assertRaises(Exception):
        db.commit()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/Scripts/python.exe -m unittest evidence_collector.tests.test_database_models -v`

Expected: import failure because `EvidenceRun` and `EvidenceDocument` do not exist.

- [ ] **Step 3: Define the six `evidence_*` tables**

Implement `EvidenceRun`, `EvidenceQuery`, `EvidenceDocument`, `EvidenceItem`, `EvidenceVerification`, and `EvidenceDeliveryBatch` in `evidence_collector/models.py`. Use UTC `created_at`/`updated_at` timestamps and these controlled string values:

```python
RUN_STATUSES = {"created", "running", "completed", "failed"}
ITEM_STATUSES = {"discovered", "rejected", "uncertain", "verified", "pending_review", "approved", "rejected_by_admin", "delivered"}
SOURCE_TYPES = {"official_notice", "news"}
```

`EvidenceDocument` must have `UniqueConstraint("source_type", "canonical_url", name="ux_evidence_document_source_canonical_url")`. `EvidenceItem` must store all audit fields from the approved design: source URL, domain, type, published/retrieved timestamps, quote, scope decision/reasons, provider/model, prompt version, verification status and score. `EvidenceDeliveryBatch` stores `evidence_item_id`, `approved_by`, `raw_post_id`, `delivery_status`, and a non-secret delivery error message.

- [ ] **Step 4: Add explicit initialization**

```python
# scripts/init_evidence_db.py
from evidence_collector.database import Base, build_session_factory
import evidence_collector.models  # noqa: F401


def main() -> None:
    session_factory = build_session_factory()
    Base.metadata.create_all(session_factory.kw["bind"])
    print("evidence collector tables are ready")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run model tests**

Run: `./.venv/Scripts/python.exe -m unittest evidence_collector.tests.test_database_models -v`

Expected: `OK`, including duplicate canonical URL rejection.

- [ ] **Step 6: Commit schema work**

```bash
git add evidence_collector/models.py evidence_collector/database.py evidence_collector/tests/test_database_models.py scripts/init_evidence_db.py
git commit -m "feat(evidence): add auditable evidence tables"
```

### Task 3: Implement pure URL, source and SYSU scope policies

**Files:**
- Create: `evidence_collector/services/canonicalize.py`
- Create: `evidence_collector/services/scope_policy.py`
- Create: `evidence_collector/tests/test_scope_policy.py`

- [ ] **Step 1: Write failing policy tests**

```python
from evidence_collector.services.scope_policy import assess_scope


def test_official_sysu_quote_is_accepted():
    result = assess_scope(
        source_type="official_notice",
        source_domain="www.sysu.edu.cn",
        title="中山大学关于校园交通的通知",
        evidence_quote="中山大学现发布校园交通调整通知。",
    )
    assert result.decision == "accepted"


def test_ambiguous_zhongda_is_uncertain():
    result = assess_scope(
        source_type="news",
        source_domain="news.example.cn",
        title="中大学生讨论交通",
        evidence_quote="中大学生表示关注。",
    )
    assert result.decision == "uncertain"


def test_missing_quote_is_rejected():
    result = assess_scope("news", "news.example.cn", "中山大学消息", "")
    assert result.decision == "rejected"
```

- [ ] **Step 2: Run the policy tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m unittest evidence_collector.tests.test_scope_policy -v`

Expected: import failure because `assess_scope` is missing.

- [ ] **Step 3: Implement deterministic rules before any model decision**

`canonicalize_url(url)` must reject non-HTTP(S) schemes, lower-case the host, remove URL fragments, remove known tracking query parameters (`utm_*`, `spm`, `from`), and return the normalized URL. `stable_external_id(url)` must return `hashlib.sha256(canonicalize_url(url).encode("utf-8")).hexdigest()`.

`assess_scope` must return a dataclass with `decision` and non-empty `reasons` using these rules in order:

```python
if not evidence_quote.strip():
    return ScopeDecision("rejected", ("missing_evidence_quote",))
if source_type not in {"official_notice", "news"}:
    return ScopeDecision("rejected", ("source_type_not_allowed",))
if "中山大学" in (title + evidence_quote) or "sun yat-sen university" in (title + evidence_quote).lower():
    return ScopeDecision("accepted", ("explicit_sysu_entity",))
if "中大" in (title + evidence_quote):
    return ScopeDecision("uncertain", ("ambiguous_zhongda_entity",))
return ScopeDecision("rejected", ("missing_sysu_entity",))
```

- [ ] **Step 4: Run tests and commit**

Run: `./.venv/Scripts/python.exe -m unittest evidence_collector.tests.test_scope_policy -v`

Expected: `OK`.

```bash
git add evidence_collector/services/canonicalize.py evidence_collector/services/scope_policy.py evidence_collector/tests/test_scope_policy.py
git commit -m "feat(evidence): enforce deterministic sysu scope policy"
```

### Task 4: Define provider contracts and disabled-safe registry

**Files:**
- Create: `evidence_collector/services/providers.py`
- Create: `evidence_collector/tests/test_providers.py`
- Modify: `evidence_collector/schemas.py`

- [ ] **Step 1: Write failing registry tests**

```python
from evidence_collector.services.providers import SearchHit, build_registry


def test_registry_has_only_enabled_provider_ids():
    registry = build_registry({"kimi": object()})
    assert registry.enabled_ids == ("kimi",)


def test_search_hit_requires_http_url_and_quote():
    with __import__("unittest").TestCase().assertRaises(ValueError):
        SearchHit(title="x", url="file:///secret", evidence_quote="")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/Scripts/python.exe -m unittest evidence_collector.tests.test_providers -v`

Expected: import failure because the provider module does not exist.

- [ ] **Step 3: Implement provider-neutral interfaces**

Create immutable `SearchHit`, `SearchRequest`, `SearchProvider` protocol, `DisabledProviderError`, and `ProviderRegistry`. The registry must expose only providers whose settings have both non-empty API key and `web_search_enabled=True`; it must never log keys. Each real adapter must normalize its vendor response into `SearchHit` and reject hits without an HTTP(S) URL or evidence quote. Add five named adapter factories (`deepseek`, `glm`, `kimi`, `doubao`, `qwen`) registered only after a capability probe confirms that the configured model returns citations.

The first implementation must include `StaticSearchProvider` for tests and local demos. It returns fixture hits and does not make network calls.

- [ ] **Step 4: Add the provider capability probe contract**

```python
class SearchProvider(Protocol):
    provider_id: str
    async def search(self, request: SearchRequest) -> list[SearchHit]: ...
    async def probe(self) -> bool: ...
```

`probe()` succeeds only when the response contains at least one valid `SearchHit`; model names alone do not enable a provider. This prevents treating ordinary chat completion as verified web search.

- [ ] **Step 5: Run tests and commit**

Run: `./.venv/Scripts/python.exe -m unittest evidence_collector.tests.test_providers -v`

Expected: `OK` with no external network calls.

```bash
git add evidence_collector/schemas.py evidence_collector/services/providers.py evidence_collector/tests/test_providers.py
git commit -m "feat(evidence): add provider registry and citation contract"
```

### Task 5: Build collection, verification, de-duplication and review state transitions

**Files:**
- Create: `evidence_collector/services/verification.py`
- Create: `evidence_collector/services/collection.py`
- Create: `evidence_collector/tests/test_collection.py`
- Modify: `evidence_collector/models.py`

- [ ] **Step 1: Write failing orchestration tests**

```python
def test_collection_stores_only_accepted_verified_candidates(db, static_provider):
    run = create_run(db, topic="中山大学校园交通", providers=["static"])
    execute_run(db, run.id, registry={"static": static_provider})
    items = db.query(EvidenceItem).all()
    assert [item.review_status for item in items] == ["pending_review"]
    assert items[0].scope_decision == "accepted"


def test_collection_keeps_ambiguous_hit_out_of_review_queue(db, ambiguous_provider):
    run = create_run(db, topic="中大交通", providers=["static"])
    execute_run(db, run.id, registry={"static": ambiguous_provider})
    assert db.query(EvidenceItem).one().review_status == "uncertain"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `./.venv/Scripts/python.exe -m unittest evidence_collector.tests.test_collection -v`

Expected: import failure for `create_run` and `execute_run`.

- [ ] **Step 3: Implement state-safe orchestration**

`create_run` must create `EvidenceRun(status="created")` and one `EvidenceQuery` per provider/query pair. `execute_run` must set the run to `running`, call each enabled provider independently, store raw candidate metadata without secrets, canonicalize URLs, use `assess_scope`, and merge the rule result with the verifier result:

```python
if scope.decision == "accepted" and verifier.status == "verified":
    item.review_status = "pending_review"
elif scope.decision == "uncertain" or verifier.status == "uncertain":
    item.review_status = "uncertain"
else:
    item.review_status = "rejected"
```

Each provider failure updates only its `EvidenceQuery` to `failed` with a sanitized error summary. The run becomes `completed` when at least one query succeeds, otherwise `failed`. Duplicate canonical URLs must reuse the existing document and never create a second active item for the same run.

- [ ] **Step 4: Add explicit administrator review transition**

```python
def review_item(db, item_id: int, approved: bool, actor: str, note: str) -> EvidenceItem:
    item = db.get(EvidenceItem, item_id)
    if item is None or item.review_status != "pending_review":
        raise ValueError("item is not reviewable")
    item.review_status = "approved" if approved else "rejected_by_admin"
    item.reviewed_by, item.review_note = actor, note.strip()
    return item
```

- [ ] **Step 5: Run tests and commit**

Run: `./.venv/Scripts/python.exe -m unittest evidence_collector.tests.test_collection -v`

Expected: `OK`; static fixtures must prove that rejected and uncertain records cannot become `pending_review`.

```bash
git add evidence_collector/services/collection.py evidence_collector/services/verification.py evidence_collector/models.py evidence_collector/tests/test_collection.py
git commit -m "feat(evidence): add reviewed evidence collection pipeline"
```

### Task 6: Expose the collector through a token-protected internal API

**Files:**
- Create: `evidence_collector/main.py`
- Create: `evidence_collector/tests/test_internal_api.py`
- Modify: `evidence_collector/schemas.py`
- Modify: `evidence_collector/services/delivery.py`

- [ ] **Step 1: Write failing API authorization and payload tests**

```python
def test_internal_routes_reject_missing_service_token(client):
    response = client.get("/internal/runs")
    assert response.status_code == 401


def test_approved_item_delivery_payload_has_no_secret_fields(client, approved_item):
    response = client.get(f"/internal/deliveries/{approved_item.id}", headers={"X-Evidence-Token": "test-token"})
    assert response.status_code == 200
    assert response.json()["canonical_url"] == approved_item.canonical_url
    assert "api_key" not in response.text.lower()
```

- [ ] **Step 2: Run API tests to verify failure**

Run: `./.venv/Scripts/python.exe -m unittest evidence_collector.tests.test_internal_api -v`

Expected: connection/import failure because the collector app does not exist.

- [ ] **Step 3: Add the internal API surface**

Implement only these token-protected endpoints:

```text
POST  /internal/runs                         create and execute an on-demand run
GET   /internal/runs                         paginate runs
GET   /internal/items                        filter by run_id and review_status
PATCH /internal/items/{item_id}/review       approve, reject, or retain uncertain item
GET   /internal/deliveries/{item_id}          return one approved, non-secret import payload
POST  /internal/deliveries/{item_id}/ack      record a committed raw_post_id
GET   /health                                 return collector health and enabled provider ids only
```

Use `X-Evidence-Token` with `hmac.compare_digest`; reject a blank configured token at application startup. `GET /internal/deliveries/{item_id}` must reject non-approved or already-invalid items with `409` and return the exact fields required by the backend import service.

- [ ] **Step 4: Run tests and commit**

Run: `./.venv/Scripts/python.exe -m unittest evidence_collector.tests.test_internal_api evidence_collector.tests.test_delivery -v`

Expected: `OK`; missing/incorrect tokens return `401` and no route leaks configuration secrets.

```bash
git add evidence_collector/main.py evidence_collector/schemas.py evidence_collector/services/delivery.py evidence_collector/tests
git commit -m "feat(evidence): expose secured collector internal api"
```

### Task 7: Add authenticated main-backend proxy routes and the sole importer

**Files:**
- Create: `backend/services/evidence_collector_client.py`
- Create: `backend/services/evidence_import_service.py`
- Create: `backend/routers/admin_evidence.py`
- Modify: `backend/main.py`
- Create: `backend/tests/test_admin_evidence.py`
- Create: `backend/tests/test_evidence_import.py`

- [ ] **Step 1: Write failing import idempotency tests**

```python
def test_import_approved_payload_creates_web_evidence_raw_post(db, mock_collector):
    result = import_evidence_item(db, item_id=7, actor="admin", collector=mock_collector)
    row = db.query(RawPost).one()
    assert row.platform == "web_evidence"
    assert row.source_table == "evidence_item"
    assert row.source_raw_id == "7"
    assert row.external_id == result.external_id


def test_second_import_reuses_same_raw_post(db, mock_collector):
    first = import_evidence_item(db, item_id=7, actor="admin", collector=mock_collector)
    second = import_evidence_item(db, item_id=7, actor="admin", collector=mock_collector)
    assert first.raw_post_id == second.raw_post_id
    assert db.query(RawPost).count() == 1
```

- [ ] **Step 2: Run tests to verify failure**

Run: `./.venv/Scripts/python.exe -m unittest backend.tests.test_evidence_import backend.tests.test_admin_evidence -v`

Expected: import failure because the import service and router do not exist.

- [ ] **Step 3: Implement collector client and importer**

`EvidenceCollectorClient` uses the existing `requests` dependency, reads `EVIDENCE_COLLECTOR_BASE_URL` and `EVIDENCE_COLLECTOR_TOKEN`, sets `X-Evidence-Token`, and has a fixed 15-second timeout. It must expose `create_run`, `list_runs`, `list_items`, `review_item`, `get_delivery_payload`, and `ack_delivery`. It must sanitize non-2xx response bodies before raising an error.

`import_evidence_item` must retrieve an approved delivery payload, compute `stable_external_id = sha256(canonical_url)`, and use the existing unique pair `(platform, external_id)`:

```python
row = db.query(RawPost).filter_by(platform="web_evidence", external_id=stable_external_id).one_or_none()
if row is None:
    row = RawPost(
        platform="web_evidence", external_id=stable_external_id,
        source_table="evidence_item", source_raw_id=str(payload["item_id"]),
        source_keyword=payload["topic"], title=payload["title"],
        content=payload["summary"], author=payload.get("publisher", ""),
        publish_time=payload.get("published_at"), url=payload["source_url"],
        raw_url=payload["source_url"], crawl_time=payload["retrieved_at"],
        raw_json=json.dumps(payload["provenance"], ensure_ascii=False), status="active",
    )
    db.add(row)
    db.flush()
```

Commit the main-database transaction before calling `ack_delivery(raw_post_id)`. If acknowledgement fails, return the persisted `raw_post_id`; a retry must reuse the unique raw post and re-attempt acknowledgement.

- [ ] **Step 4: Add administrator-only proxy router**

Add `backend/routers/admin_evidence.py` with `require_admin` on every route:

```text
POST  /admin/evidence/runs
GET   /admin/evidence/runs
GET   /admin/evidence/items
PATCH /admin/evidence/items/{item_id}/review
POST  /admin/evidence/items/{item_id}/import
```

Return all payloads through existing `backend.schemas.ok`. Include `admin_evidence_router` in `backend/main.py` with the existing `/api` prefix. Do not add any route or import under `MediaCrawler`.

- [ ] **Step 5: Run backend tests and commit**

Run: `./.venv/Scripts/python.exe -m unittest backend.tests.test_evidence_import backend.tests.test_admin_evidence -v`

Expected: `OK`; non-admin API requests are forbidden and duplicate import creates one raw record.

```bash
git add backend/main.py backend/routers/admin_evidence.py backend/services/evidence_collector_client.py backend/services/evidence_import_service.py backend/tests/test_admin_evidence.py backend/tests/test_evidence_import.py
git commit -m "feat(admin): add reviewed evidence import bridge"
```

### Task 8: Add one administrator evidence workspace to the Vue frontend

**Files:**
- Modify: `frontend/src/api/admin.js`
- Modify: `frontend/src/router/index.js`
- Create: `frontend/src/views/AdminEvidenceView.vue`
- Test: `frontend/package.json` build script

- [ ] **Step 1: Add failing API-shape expectations as backend tests**

Extend `backend/tests/test_admin_evidence.py` so an administrator listing response asserts the existing API envelope and item fields used by the UI:

```python
payload = response.json()["data"]
self.assertIn("items", payload)
self.assertIn("review_status", payload["items"][0])
self.assertIn("evidence_quote", payload["items"][0])
self.assertIn("scope_reasons", payload["items"][0])
```

- [ ] **Step 2: Verify the API test fails until serialization is complete**

Run: `./.venv/Scripts/python.exe -m unittest backend.tests.test_admin_evidence -v`

Expected: assertion failure for a missing evidence field.

- [ ] **Step 3: Extend the established administrator client**

Add these functions to `frontend/src/api/admin.js`:

```javascript
export const createEvidenceRun = (payload) => http.post('/admin/evidence/runs', payload)
export const fetchEvidenceRuns = (params = {}) => http.get('/admin/evidence/runs', { params })
export const fetchEvidenceItems = (params = {}) => http.get('/admin/evidence/items', { params })
export const reviewEvidenceItem = (id, payload) => http.patch(`/admin/evidence/items/${id}/review`, payload)
export const importEvidenceItem = (id) => http.post(`/admin/evidence/items/${id}/import`)
```

- [ ] **Step 4: Implement the admin-only view and route**

Add `AdminEvidenceView` at `/admin/evidence` with four sections in one page: new task form, task list, reviewable evidence table, and delivery outcome. Every evidence row must visibly show title, source URL, source type, quote, scope reasons, verifier result, provider/model, review note, and import state. The only action buttons are “approve”, “reject”, “keep uncertain”, and “import approved item”. Do not include auto-run or auto-import controls.

Add the admin-only route beside the other `/admin/*` routes in `frontend/src/router/index.js`. Reuse existing `.admin-page`, `.panel-card`, `.compact-table`, Element Plus loading, message, and error patterns from `AdminKeywordsView.vue`.

- [ ] **Step 5: Run the backend contract test and frontend build**

Run: `./.venv/Scripts/python.exe -m unittest backend.tests.test_admin_evidence -v`

Expected: `OK`.

Run: `cd frontend && npm run build`

Expected: Vite completes with `✓ built` and creates `frontend/dist`.

- [ ] **Step 6: Commit UI work**

```bash
git add frontend/src/api/admin.js frontend/src/router/index.js frontend/src/views/AdminEvidenceView.vue backend/tests/test_admin_evidence.py
git commit -m "feat(admin): add evidence collection workspace"
```

### Task 9: Add runbook, provider verification procedure, and end-to-end safety checks

**Files:**
- Create: `docs/evidence-collector-runbook.md`
- Modify: `.env.example`
- Create: `evidence_collector/tests/test_delivery.py`
- Modify: `backend/tests/test_evidence_import.py`

- [ ] **Step 1: Write a failing no-unapproved-import test**

```python
def test_import_refuses_unapproved_delivery(db, mock_collector):
    mock_collector.get_delivery_payload.side_effect = CollectorConflict("item is not approved")
    with __import__("unittest").TestCase().assertRaises(CollectorConflict):
        import_evidence_item(db, item_id=9, actor="admin", collector=mock_collector)
    __import__("unittest").TestCase().assertEqual(db.query(RawPost).count(), 0)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `./.venv/Scripts/python.exe -m unittest backend.tests.test_evidence_import evidence_collector.tests.test_delivery -v`

Expected: failure until conflict handling preserves the empty main table.

- [ ] **Step 3: Document exact operator workflow**

Write `docs/evidence-collector-runbook.md` with these executable sections: initialize `evidence_*` tables; start collector on a configured localhost port; configure one provider at a time using environment variables; run `/health` to see enabled IDs only; run a low-limit administrator task; inspect evidence URLs and quotes; approve one item; import it; run existing `scripts/process_raw_posts.py`; inspect the resulting raw and processed record; disable a provider by setting its web-search flag false.

The provider verification section must require a successful citation-bearing `probe()` before enabling a provider. It must explicitly say that an ordinary chat-completions response or a model list response is not sufficient proof of web-search capability. It must also state that no production API key is used by unit/integration tests.

- [ ] **Step 4: Make failure behavior pass and run the full focused suite**

Run: `./.venv/Scripts/python.exe -m unittest discover -s evidence_collector/tests -v`

Expected: all collector tests pass without network access.

Run: `./.venv/Scripts/python.exe -m unittest backend.tests.test_evidence_import backend.tests.test_admin_evidence -v`

Expected: all bridge tests pass; rejected, uncertain, and unapproved records leave `raw_posts` unchanged.

Run: `git diff -- MediaCrawler`

Expected: no output.

- [ ] **Step 5: Commit the operating guidance and safety tests**

```bash
git add docs/evidence-collector-runbook.md .env.example evidence_collector/tests/test_delivery.py backend/tests/test_evidence_import.py
git commit -m "docs: add evidence collector runbook and safety checks"
```

## Completion verification

- [ ] Run `./.venv/Scripts/python.exe -m unittest discover -s evidence_collector/tests -v` and record a passing result.
- [ ] Run `./.venv/Scripts/python.exe -m unittest backend.tests.test_evidence_import backend.tests.test_admin_evidence -v` and record a passing result.
- [ ] Run `cd frontend && npm run build` and record a successful Vite build.
- [ ] Run `git diff --exit-code -- MediaCrawler` and confirm it exits `0`.
- [ ] Start only the collector in a local, no-key configuration and confirm `/health` reports no enabled providers without exposing any secret.
