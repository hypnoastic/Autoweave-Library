# AutoWeave Diagrams Source

Version: 2.0
Purpose: text-first diagrams for coding agents and PDF generation.

---

## 1. System context

```text
Human / Main Product / CLI
  -> AutoWeave Orchestrator
     -> Config Compiler
     -> Context Service
     -> Artifact Registry
     -> Approval Service
     -> Event / Observability Service
     -> Postgres + pgvector
     -> Redis + Celery
     -> Neo4j
     -> OpenHands agent-server workers
        -> isolated sandbox/worktree per task attempt
        -> Vertex AI model calls through injected worker credentials
```

```mermaid
flowchart TD
    H[Human / Main Product / CLI] --> O[AutoWeave Orchestrator]
    O --> CC[Config Compiler]
    O --> CS[Context Service]
    O --> AR[Artifact Registry]
    O --> AP[Approval Service]
    O --> EV[Observability Service]
    O --> PG[(Postgres + pgvector)]
    O --> RD[(Redis)]
    O --> CY[Celery]
    O --> N4[(Neo4j)]
    O --> OH[OpenHands Remote Workers]
    OH --> SB[Isolated sandbox/worktree]
    OH --> VX[Vertex AI]
```

---

## 2. Manager -> backend/frontend -> integration -> review

```mermaid
flowchart LR
    H[Human task] --> M[Manager attempt]
    M --> G[Persist graph revision]
    G --> BC[backend_contract]
    G --> FU[frontend_ui]
    BC --> BI[backend_impl]
    BI --> IN[integration]
    FU --> IN
    IN --> RV[review]
    RV --> DONE[complete]
```

---

## 3. Dynamic scheduling rules

```text
If all hard dependencies complete and no approval/human gate blocks the task,
then the task becomes READY and the scheduler may fan it out immediately.
Only downstream chains of blocked tasks pause.
Unrelated branches continue.
```

```mermaid
flowchart TD
    A[Task A ready] --> RA[Run A]
    B[Task B ready] --> RB[Run B]
    RA --> C{Unlocks Task C?}
    RB --> D{Unlocks Task D?}
    C -->|yes| RC[Run C]
    D -->|blocked on human| WH[waiting_for_human]
    RC --> E[Continue unrelated branch]
```

---

## 4. Artifact handoff

```mermaid
flowchart LR
    PA[Producing agent] --> PUT[put_artifact]
    PUT --> REG[Artifact Registry]
    REG --> ORC[Orchestrator dependency + visibility resolver]
    ORC --> GET[get_upstream_artifacts]
    GET --> DA[Downstream agent]
```

---

## 5. Human-in-the-loop

```mermaid
flowchart TD
    AG[Worker attempt] --> Q[request_clarification / approval / blocker]
    Q --> OR[Orchestrator validates]
    OR --> HR[HumanRequest or ApprovalRequest]
    HR --> MG[Manager formats human-facing question]
    MG --> HU[Human answer]
    HU --> OR2[Orchestrator records answer]
    OR2 --> RS[Resume correct attempt or create retry]
```

---

## 6. Context resolution stack

```text
1. workspace/live files
2. Postgres structured records
3. pgvector semantic retrieval
4. artifact store
5. Neo4j traversal
6. Redis live state
7. typed miss / human escalation
```

```mermaid
flowchart LR
    Q[Context query] --> W[Workspace]
    W -->|miss| P[Postgres]
    P -->|miss| V[pgvector]
    V -->|miss| A[Artifact Store]
    A -->|miss| G[Neo4j]
    G -->|miss| R[Redis]
    R -->|miss| M[Typed miss / escalate]
```

---

## 7. Observability export

```mermaid
flowchart TD
    OH[OpenHands events + spans] --> WA[Worker Adapter]
    WA --> DE[Domain events]
    WA --> SP[OpenTelemetry spans]
    WA --> MT[Metrics]
    DE --> PG[(Postgres event log)]
    SP --> OT[OTLP backend]
    MT --> MB[Metrics backend]
    PG --> API[Query + live stream API]
    API --> MP[Main product timeline / audit]
```

---

## 8. Core domain classes

```mermaid
classDiagram
    class Project
    class Team
    class AgentDefinition
    class WorkflowDefinition
    class WorkflowRun
    class Task
    class TaskEdge
    class TaskAttempt
    class Artifact
    class Decision
    class MemoryEntry
    class HumanRequest
    class ApprovalRequest
    class Event
    class ModelRoute
    class WorkspaceRecord

    Project --> Team
    Project --> AgentDefinition
    Project --> WorkflowDefinition
    WorkflowDefinition --> WorkflowRun
    WorkflowRun --> Task
    Task --> TaskEdge
    Task --> TaskAttempt
    TaskAttempt --> Artifact
    TaskAttempt --> Decision
    WorkflowRun --> Event
    Task --> HumanRequest
    Task --> ApprovalRequest
    TaskAttempt --> ModelRoute
    TaskAttempt --> WorkspaceRecord
```

---

## 9. Service classes

```mermaid
classDiagram
    class OrchestratorService
    class WorkflowEngine
    class Scheduler
    class WorkerManager
    class ConfigCompiler
    class ContextService
    class ArtifactRegistry
    class ApprovalService
    class EventService
    class ModelRouter
    class GraphProjectionService
    class ObservabilityExporter
    class StorageUnitOfWork

    OrchestratorService --> WorkflowEngine
    OrchestratorService --> Scheduler
    OrchestratorService --> WorkerManager
    OrchestratorService --> ContextService
    OrchestratorService --> ArtifactRegistry
    OrchestratorService --> ApprovalService
    OrchestratorService --> EventService
    OrchestratorService --> ModelRouter
    OrchestratorService --> GraphProjectionService
    OrchestratorService --> ObservabilityExporter
    OrchestratorService --> StorageUnitOfWork
    WorkerManager --> ConfigCompiler
```

---

## 10. Worker lifecycle

```mermaid
sequenceDiagram
    participant O as Orchestrator
    participant DB as Postgres
    participant RD as Redis
    participant C as Compiler
    participant W as OpenHands Worker
    participant V as Vertex AI

    O->>DB: create task_attempt
    O->>RD: acquire lease + heartbeat
    O->>C: compile canonical config
    C-->>O: compiled OpenHands config
    O->>W: launch remote worker
    W->>V: model calls via injected credentials
    W-->>O: events, artifacts, summaries
    O->>DB: finalize attempt state
    O->>RD: release lease
```
