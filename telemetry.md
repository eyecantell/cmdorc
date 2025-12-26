### High-Level Design/Plan for Telemetry/Metrics (targeted for 0.x.0)

#### 1. **Design Principles**
   - **Privacy-First:** Opt-in only; no data leaves the machine without explicit consent. Use anonymization (hashing, aggregation) at higher levels.
   - **Modularity:** TelemetryReporter as an ABC, injectable like CommandExecutor. Payload building separate from reporting.
   - **Testability:** Pure functions for payload building; mock reporters for integration tests.
   - **Config Immutability:** TelemetryConfig is frozen dataclass, loaded from TOML.
   - **Minimal Overhead:** When disabled, zero allocations or calls. Async-friendly to not block orchestration.
   - **Extensibility:** Easy to add reporters (e.g., Prometheus for metrics integration).
   - **Anti-Patterns to Avoid:** No global state; no synchronous I/O; no leaking PII.

#### 2. **Components**
   - **TelemetryConfig (frozen dataclass):**
     - Fields: `enabled: bool = False`, `level: TelemetryLevel = TelemetryLevel.MINIMAL` (enum: OFF, MINIMAL, STANDARD, DEBUG), `endpoint: str | None = None` (for HTTP), `local_file: Path | None = None` (for file logging), `debug_consent_given: bool = False`, `debug_consent_expires: datetime | None = None`.
     - Loaded via `load_telemetry_config(path)` or from RunnerConfig's [telemetry] section.
   - **TelemetryLevel (Enum):** OFF, MINIMAL, STANDARD, DEBUG.
   - **TelemetryPayloadBuilder:**
     - Builds dict payloads based on level, runtime state (e.g., from CommandRuntime), and event data.
     - Methods: `build_startup_payload()`, `build_command_completed_payload(result: RunResult, manual: bool)`, etc.
     - Anonymizes: e.g., `hash_item(item: str) -> str` using HMAC-SHA256 with local salt (generated once and stored in ~/.cmdorc/telemetry_salt).
   - **TelemetryReporter (ABC):**
     - `async def report(self, event: str, payload: dict) -> None`
     - `async def close(self) -> None` (for cleanup, e.g., flush file).
   - **Implementations:**
     - `NoopReporter`: Does nothing.
     - `HttpReporter`: Uses aiohttp to POST JSON to endpoint; batches if multiple reports queue up (simple queue to avoid floods).
     - `LocalFileReporter`: Appends JSONL to file; rotates if >1MB.
   - **Install ID & Salt Generation:** On first opt-in, generate UUID for install_id and random salt for hashing; store in ~/.cmdorc/ (user-owned dir).

#### 3. **Integration with cmdorc**
   - **CommandOrchestrator:**
     - Add param: `telemetry_reporter: TelemetryReporter | None = None` (defaults to NoopReporter).
     - In `__init__`: If enabled, report "orchestrator_started".
     - In execution flow: After run finalizes (in _watch_completion or similar), report "command_completed".
     - In trigger: Optionally report "trigger_fired" at STANDARD+ levels (aggregated, e.g., trigger_count).
     - Shutdown: Call `await telemetry_reporter.close()`.
   - **Config Loading:** Extend `load_config()` to parse [telemetry] section into TelemetryConfig.
   - **CLI Integration:** Add subcommands under `cmdorc telemetry` (using argparse or click; prudent choice: click for cleanliness).
     - `status`: Print config + last report time.
     - `opt-in [--level=minimal|standard|debug]`: Enable, set level, prompt for debug consent if needed, generate IDs.
     - `opt-out`: Disable, delete local files.
     - `show-payload [event]`: Simulate and print a sample payload for the event (e.g., "command_completed").
   - **Events to Track:** Keep minimal — "orchestrator_started", "command_completed", "trigger_fired" (at higher levels). No more than 5 total.

#### 4. **Payload Structures**
   - **All Levels:** Include `event`, `cmdorc_version`, `python_version`, `os`, `arch`, `anonymous_install_id`, `timestamp`.
   - **MINIMAL:** + `executor_type`, `command_count`, `has_triggers: bool`.
   - **STANDARD:** + Aggregates like `trigger_count`, `has_wildcard_triggers: bool`, `avg_concurrent_runs`, `most_common_on_retrigger_policy`.
   - **DEBUG:** + Hashed specifics like `hashed_command_name`, `hashed_trigger_patterns: list[str]`, `command_arg_count: int`, `hashed_cwd_prefix: str`.

#### 5. **API Endpoint (Server Side)**
   - Minimal FastAPI app (separate repo/project: cmdorc-telemetry-server).
   - Endpoint: POST /v1/report — accepts JSON, validates schema, stores in DB (e.g., SQLite or Postgres for simplicity).
   - Response: Optional { "message": "Thanks!", "stats": { "percentile_duration": 87 } } for user value.
   - Security: Rate-limit by install_id; no auth needed since data is anon.
   - Deployment: Heroku/free tier for MVP; log to BigQuery later if scale.

#### 6. **Security & Privacy**
   - No PII ever.
   - HTTPS only.
   - Local storage: Mode 600 permissions.
   - Consent: Debug level prompts "This sends hashed command info — confirm? (expires in 30 days)".
   - Auditing: Log all reports locally if LOCAL reporter enabled.

#### 7. **Implementation Steps**
   - **Phase 1:** Define dataclass/enum/ABC in telemetry.py; implement builders/reporters (target: <200 LOC).
   - **Phase 2:** Integrate into Orchestrator/Runtime (add hooks, preserve existing tests).
   - **Phase 3:** CLI subcommands + config loading.
   - **Phase 4:** Tests (100% coverage: unit for builders, integration with MockReporter).
   - **Phase 5:** Server sketch (optional, but I'll include in telemetry.md).
   - Total Effort: ~1-2 days; no refactoring needed beyond minor Orchestrator additions (maintain docstrings/logs).

This plan is prudent: Adds value without bloat, fully backward-compatible. If it looks solid, we can proceed to code — but let's confirm/refine first.

Now, as requested, here's the **telemetry.md** content. I've modeled it after architecture.md: authoritative, structured, with sections for principles, API, components, etc. This serves as the single source of truth.

<DOCUMENT filename="telemetry.md">
# cmdorc Telemetry Reference

**Version:** 0.1.0  
**Status:** Authoritative design document for telemetry feature

This is the single source of truth for cmdorc's telemetry system, including configuration, components, and integration.

---

## Table of Contents

1. [Design Principles](#design-principles)
2. [Public API](#public-api)
3. [Core Components](#core-components)
4. [Configuration](#configuration)
5. [Payload Structures](#payload-structures)
6. [Integration Points](#integration-points)
7. [CLI Commands](#cli-commands)
8. [Reporters](#reporters)
9. [Privacy & Security](#privacy--security)
10. [Server-Side Endpoint](#server-side-endpoint)
11. [Testing Strategy](#testing-strategy)
12. [Implementation Checklist](#implementation-checklist)

---

## 1. Design Principles

### Core Values
- **Privacy by Default:** Completely opt-in; disabled means zero overhead.
- **Transparency:** Users can inspect exact payloads; no hidden data.
- **Modularity:** Swappable reporters; separate payload building.
- **Minimalism:** Few events; aggregated/anonymized data.
- **Async-Friendly:** No blocking I/O.
- **Testability:** Mockable interfaces; pure functions.

### Anti-Patterns to Avoid
- ❌ Sending data without consent.
- ❌ Raw PII or command content.
- ❌ Global state for IDs/salts.
- ❌ Synchronous reporting.
- ❌ Over-collection (stick to defined levels).

---

## 2. Public API

Telemetry is injected via CommandOrchestrator:

```python
orchestrator = CommandOrchestrator(
    ...,
    telemetry_reporter: TelemetryReporter | None = None  # Defaults to NoopReporter
)
```

No direct public methods; all reporting is internal hooks.

---

## 3. Core Components

### Component Hierarchy

```
CommandOrchestrator (injects reporter)
├── TelemetryPayloadBuilder (builds level-specific payloads)
└── TelemetryReporter (ABC for sending)
    ├── NoopReporter
    ├── HttpReporter
    └── LocalFileReporter
```

### Responsibilities

| Component | Owns | Does NOT Own |
|-----------|------|--------------|
| **TelemetryPayloadBuilder** | Payload construction, anonymization (hashing) | Sending data, config parsing |
| **TelemetryReporter** | Data transmission (HTTP, file, etc.) | Payload logic, state management |
| **CommandOrchestrator** | Reporting hooks (e.g., on startup/completion) | Telemetry config, building payloads |

---

## 4. Configuration

### TelemetryConfig (frozen dataclass)

```python
from enum import Enum
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field

class TelemetryLevel(Enum):
    OFF = "off"
    MINIMAL = "minimal"
    STANDARD = "standard"
    DEBUG = "debug"

@dataclass(frozen=True)
class TelemetryConfig:
    enabled: bool = False
    level: TelemetryLevel = TelemetryLevel.MINIMAL
    endpoint: str | None = "https://telemetry.cmdorc.dev/v1"
    local_file: Path | None = None
    debug_consent_given: bool = False
    debug_consent_expires: datetime | None = None
```

**Validation (in __post_init__):**
- If level == DEBUG, require debug_consent_given=True and non-expired consent.
- If enabled, require endpoint or local_file.

**Loading:** Extend load_config() to parse [telemetry] section.

---

## 5. Payload Structures

Base payload (all levels > OFF):

```json
{
  "event": "orchestrator_started",
  "cmdorc_version": "0.1.0",
  "python_version": "3.12",
  "os": "linux",
  "arch": "x86_64",
  "anonymous_install_id": "uuid-string",
  "timestamp": "2025-12-10T12:00:00Z"
}
```

- **MINIMAL Additions:** "executor_type", "command_count", "has_triggers".
- **STANDARD Additions:** "trigger_count", "has_wildcard_triggers", "avg_concurrent_runs", "most_common_on_retrigger_policy".
- **DEBUG Additions:** "hashed_command_name", "hashed_trigger_patterns", "command_arg_count", "hashed_cwd_prefix".

Hashing: HMAC-SHA256 with local salt, truncated to 12 hex chars.

---

## 6. Integration Points

- **Startup:** Report "orchestrator_started" with config aggregates.
- **Run Completion:** Report "command_completed" with result metrics (duration, success, etc.).
- **Trigger:** At STANDARD+, report "trigger_fired" (aggregated).
- **Shutdown:** Await reporter.close().

Use TelemetryPayloadBuilder to construct before reporting.

---

## 7. CLI Commands

Assuming click integration:

- `cmdorc telemetry status`
- `cmdorc telemetry opt-in [--level=LEVEL] [--debug]`
- `cmdorc telemetry opt-out`
- `cmdorc telemetry show-payload [EVENT]`

Prompt for debug consent; update ~/.cmdorc/config.toml.

---

## 8. Reporters

### TelemetryReporter (ABC)

```python
from abc import ABC, abstractmethod

class TelemetryReporter(ABC):
    @abstractmethod
    async def report(self, event: str, payload: dict) -> None:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass
```

- **NoopReporter:** Pass.
- **HttpReporter:** aiohttp.post(endpoint + "/report", json={"event": event, **payload}).
- **LocalFileReporter:** Append JSONL to file.

---

## 9. Privacy & Security

- **Anonymization:** Hashing with local salt; no reversibility.
- **Consent:** Explicit for DEBUG; time-bound.
- **Storage:** Local files mode 600.
- **Network:** HTTPS; no IPs logged client-side.
- **Opt-Out:** Deletes local IDs/salt.

---

## 10. Server-Side Endpoint

Minimal FastAPI example:

```python
from fastapi import FastAPI, Request
import sqlite3

app = FastAPI()
db = sqlite3.connect("telemetry.db")

@app.post("/v1/report")
async def report(request: Request):
    data = await request.json()
    # Validate & insert into DB
    db.execute("INSERT INTO reports VALUES (?, ?)", (data["event"], str(data)))
    db.commit()
    return {"message": "Thanks!", "stats": {"percentile": 50}}  # Placeholder
```

Deploy with uvicorn; add rate-limiting.

---

## 11. Testing Strategy

- **Unit:** PayloadBuilder (all levels, hashing).
- **Integration:** MockReporter in Orchestrator tests.
- **End-to-End:** Simulate reports with LocalFileReporter.
- Coverage: 100%.

---

## 12. Implementation Checklist

- [ ] TelemetryConfig & Level Enum
- [ ] PayloadBuilder with hashing
- [ ] Reporter ABC & Implementations
- [ ] Orchestrator Integration
- [ ] CLI Subcommands
- [ ] Config Loading Extension
- [ ] Tests
- [ ] Server Sketch (optional)

---

**End of Telemetry Reference**