"""
Distilled Knowledge Benchmark Corpus
=====================================

30 prose documents covering cross-cutting engineering constraints, and
30 paraphrased QA pairs where the question wording deliberately avoids
the exact vocabulary in the document — testing semantic retrieval rather
than keyword matching.

Used by retrieval_bench.py and ragas_bench.py.
"""
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Corpus documents
# ---------------------------------------------------------------------------

ENTRIES: list[tuple[str, str]] = [
    ("mutex_cross_process.txt",
     "A cross-process file lock prevents two inference models from loading "
     "simultaneously on the same GPU. Without it, VRAM overflows silently and "
     "inference returns garbage instead of raising an error. The lock file lives "
     "in /tmp and is acquired with fcntl.flock before any model load."),

    ("uuid_driver_gotcha.txt",
     "The asyncpg database driver returns UUID objects natively from Postgres — "
     "never pass them through the uuid.UUID() constructor a second time because "
     "the constructor raises on an already-UUID input. This error surfaces during "
     "row-level migrations that rename or cast identifier columns."),

    ("audit_field_requirement.txt",
     "Every write to the action store must carry a security_scan_score in its "
     "metadata. Hardcoded scores of 1.0 were found in three files during an audit; "
     "the guard module now enforces the field is present and dynamically computed "
     "rather than a compile-time constant."),

    ("partitioned_table_index.txt",
     "A partitioned database table has a constraint on concurrent index creation: "
     "CREATE INDEX CONCURRENTLY cannot run on the partitioned parent. The index must "
     "be built on each individual partition first; the parent index is then "
     "automatically composed from the partition indexes."),

    ("two_tier_storage.txt",
     "The two-tier storage rule separates raw event telemetry from semantic agent "
     "memories. Raw telemetry goes to the relational database. Semantic memories go "
     "to the vector store. A pre-ingest deduplication check is mandatory before any "
     "vector store write — skip ingestion if the top-1 cosine similarity to an "
     "existing entry exceeds 0.95."),

    ("dual_confirmation_gate.txt",
     "High-risk actions require dual confirmation: operator approval plus a mandatory "
     "60-second enforced delay between approval and execution. The quorum check runs "
     "through an approval bridge service. Skipping either step is a compliance "
     "violation and must be flagged in the audit log."),

    ("kernel_probe_path_truncation.txt",
     "An eBPF LSM probe for path resolution fails on bind-mount paths because the "
     "kernel helper silently truncates beyond 256 bytes. The fix uses a two-pass "
     "approach: the kernel side records the inode, then userspace resolves the full "
     "path from the inode. This avoids the truncation limit entirely."),

    ("project_venv_shebang.txt",
     "All scripts that import project dependencies must use an explicit shebang "
     "pointing to the project virtual environment's Python interpreter. The system "
     "python3 does not have the project packages installed and will raise ImportError "
     "silently or fall back to an incompatible version."),

    ("nfs_soft_mount.txt",
     "Network-attached storage mounts using soft NFS must never be hard-depended on "
     "in real-time code paths. A stale NFS handle stalls the entire asyncio event "
     "loop indefinitely. Any NFS access should run in a background thread with a "
     "timeout so a downed storage node cannot freeze the main loop."),

    ("gpu_memory_ceiling.txt",
     "A GPU with a 24 GB VRAM ceiling requires a serialization mechanism for model "
     "loads. A lock gates concurrent agent spawns so they cannot collectively exceed "
     "the ceiling. Keep the vector store Top-K at 3 or lower to avoid embedding OOM "
     "during heavy inference workloads."),

    ("deliverable_verification.txt",
     "A deliverable verification table links to the work-item table. Each row holds "
     "sequence number, title, expected file path, minimum byte size, and status. An "
     "agent calls a completion handler per deliverable; the system verifies the file "
     "exists on disk before setting status to VERIFIED. The work-item auto-promotes "
     "when all deliverable rows reach VERIFIED."),

    ("hallucination_block_threshold.txt",
     "A pipeline stage correction function auto-sets a work item to FAILED when "
     "hallucination_count reaches the block threshold (default 5) or when "
     "skipped_steps reaches the same threshold. The threshold is configurable via "
     "an environment variable. Do not re-run manually after a block — the scheduler "
     "re-dispatches FAILED items on the next cycle."),

    ("access_ring_policy.txt",
     "Context rings gate agent read access in the vector store. Ring 1 is public "
     "(any agent), Ring 2 is confidential client data (restricted agents only), "
     "Ring 3 is financial and legal data, Ring 4 is personal data (home agent only). "
     "An access-ring filter is applied before returning any vector store payload "
     "to prevent cross-ring data leakage."),

    ("asyncio_timeout_str_bug.txt",
     "asyncio.TimeoutError.__str__() returns an empty string — using str(exc) in a "
     "log message produces a blank line that hides the root cause. Use "
     "type(exc).__name__ instead to get the exception class name. This silent failure "
     "hid timeout root causes in a service for several weeks."),

    ("file_lock_vs_asyncio_lock.txt",
     "Use file locks instead of asyncio.Lock for cross-process mutual exclusion. "
     "asyncio semaphores are process-local — subprocess boundaries destroy their "
     "scope. Any gate that must coordinate between a parent process and spawned "
     "subprocesses should use fcntl.flock on Linux."),

    ("model_tier_eviction.txt",
     "Model tier batching order is largest-first: 32b → 8b → API fallback. The "
     "coordinator evicts a model at tier boundaries with keep_alive=0 to release "
     "VRAM before loading the next tier. Streaming mode zombie processes are killed "
     "explicitly before the next model loads. Regression tests guard this ordering."),

    ("boolean_env_var_pitfall.txt",
     "bool(os.environ.get('FLAG')) evaluates the string '0' as True because any "
     "non-empty string is truthy in Python. Use an explicit allowlist instead: "
     "value not in ('', '0', 'false', 'no'). Relying on bool() for flag parsing "
     "causes DRY_RUN and similar flags to behave opposite to the operator's intent."),

    ("spec_deviation_disclosure.txt",
     "Before marking a spec-driven work item complete, an agent must self-diff: "
     "'Spec required X deliverables, I shipped Y. Substitutions: Z. Deferred: N.' "
     "Silent partial compliance is harder to catch than a crash because the output "
     "looks complete. A completion summary that does not address the spec is itself "
     "incomplete."),

    ("cursor_based_extraction.txt",
     "A memory extractor uses a UUID cursor to track the last processed message. On "
     "each periodic invocation it reads only new messages since the cursor, classifies "
     "them with a policy enforcer, and ingests approved content to the correct "
     "collection. The cursor prevents reprocessing and keeps ingestion idempotent."),

    ("proposal_engine_sources.txt",
     "An autonomous proposal engine scans five sources: error telemetry, agent "
     "failure rates, stuck work items, dead code (functions with zero inbound call "
     "edges in the call graph), and schema drift (foreign key columns missing "
     "indexes). Proposals are deduplicated before filing to avoid flooding the "
     "work-item queue with redundant entries."),

    ("package_security_pipeline.txt",
     "Every new Python package must pass three gates before production: (1) a "
     "library fetcher validates SHA256 against the package registry's published "
     "digests, (2) a detonation step runs the wheel in an isolated sandbox with "
     "a network sinkhole to detect runtime exfiltration, (3) a systemic audit "
     "scans the full requirements file for typosquats. A threat score above the "
     "threshold blocks the package."),

    ("work_item_lifecycle.txt",
     "Work item lifecycle states: PENDING → IN_PROGRESS → REVIEW_READY → COMPLETED "
     "or FAILED. PROPOSED means an AI-generated idea awaiting operator promotion — "
     "never auto-dispatched. BLOCKED means an external dependency is unresolved. "
     "CANCELLED means the operator killed it. Promotion to REVIEW_READY is blocked "
     "if any deliverable rows are unverified."),

    ("subprocess_stdout_discipline.txt",
     "A subprocess that produces machine-readable output must write JSON to stdout "
     "and diagnostic logs to stderr. If structured output lands on stderr, the "
     "caller's json.loads() receives an empty string and throws JSONDecodeError. "
     "The fix is explicit sys.stdout.write() for all machine-readable output — "
     "never rely on print()'s default stream."),

    ("partitioned_index_creation.txt",
     "CREATE INDEX CONCURRENTLY on a partitioned Postgres table must target each "
     "partition individually, not the parent. The parent index is then automatically "
     "derived from the partition indexes. Attempting CONCURRENTLY on the parent "
     "fails with an error. This affects any large table migrated to partitioning "
     "after initial deployment."),

    ("privileged_command_ott.txt",
     "Privileged host commands should route through a one-time token mechanism so "
     "the operator does not need persistent sudo. Key gotchas: use 'metadata' not "
     "'meta' in the token path, num_uses refers to invocation count not seconds, "
     "and the token is single-session — re-request if the shell restarts."),

    ("sandbox_detonation_protocol.txt",
     "All Docker and Python modifications must be validated in an isolated sandbox "
     "environment before applying to the host. The sandbox uses a network sinkhole "
     "so outbound calls are blocked during testing. This protocol applies to 'quick' "
     "changes as well — size of change does not exempt it from sandbox validation."),

    ("memory_capture_policy.txt",
     "Capture to the long-term memory store: architectural decisions and the reason "
     "behind them, failure lessons, non-obvious constraints, operator context, and "
     "work-item outcomes. Do NOT capture: code text (version control has it), raw "
     "telemetry (relational DB only), transient state, live metrics, or content that "
     "duplicates an existing reference document. Classify before ingesting."),

    ("sbom_tracking.txt",
     "After any batch of new Python packages, update the software bill-of-materials "
     "graph to keep it current. The SBOM includes SHA256 hash, registry validation "
     "date, and sandbox detonation threat score for each package. Retroactive "
     "validation is required for any package added without going through the "
     "security pipeline."),

    ("scheduler_ghost_job_handling.txt",
     "The job scheduler checks for PENDING work items every cycle and dispatches to "
     "the correct agent. Ghost jobs — work items stuck IN_PROGRESS with no heartbeat "
     "for more than 30 minutes — are automatically reset to PENDING for re-dispatch. "
     "The morning summary digest fires once at a configured time; per-spawn "
     "notifications are suppressed to prevent notification floods."),

    ("model_eviction_before_load.txt",
     "When switching model tiers, explicitly evict the outgoing model before loading "
     "the incoming one. Do not rely on automatic eviction — it is time-based, not "
     "memory-based, and will not free VRAM fast enough under concurrent load. The "
     "streaming zombie kill must complete before eviction, and eviction must "
     "complete before the next load begins."),
]

# ---------------------------------------------------------------------------
# QA pairs
# ---------------------------------------------------------------------------

@dataclass
class QAPair:
    question: str
    ground_truth_fragment: str
    paraphrase_note: str = ""


QA_PAIRS: list[QAPair] = [
    QAPair("how do we stop two AI models from loading at the same time?",
           "fcntl.flock", "'stop two models' vs 'cross-process file lock'"),
    QAPair("why shouldn't we wrap database row identifiers in the UUID constructor?",
           "already-UUID", "'database row identifiers' vs 'UUID objects'"),
    QAPair("what safety field must accompany every write to the action store?",
           "security_scan_score", "'action store', 'safety field' vs 'metadata field'"),
    QAPair("what rule decides whether agent memories go to the relational database or the vector store?",
           "two-tier storage", "'relational database or vector store' vs 'Postgres or Qdrant'"),
    QAPair("how does the kernel probe avoid getting cut off on long file paths?",
           "inode", "'cut off' vs 'truncates', 'kernel probe' vs 'eBPF LSM'"),
    QAPair("what happens after a script tries to load packages and Python can't find them?",
           "virtual environment", "shebang — indirect symptom query"),
    QAPair("what verifies that each deliverable file actually exists on disk?",
           "VERIFIED", "'verifies exists on disk' without naming the function"),
    QAPair("what crash threshold automatically kills a work item mid-run?",
           "hallucination_count", "'crash threshold' vs 'block threshold'"),
    QAPair("why is asyncio.Lock the wrong tool for preventing concurrent subprocess access?",
           "process-local", "'subprocess' + 'concurrent' vs 'cross-process'"),
    QAPair("what problem occurs when logging a timeout error and the message appears blank?",
           "type(exc).__name__", "'blank' vs 'empty string', 'logging' vs 'error log'"),
    QAPair("how can two model tiers share the GPU without running out of memory?",
           "keep_alive=0", "'share the GPU' vs 'tier boundaries'"),
    QAPair("what makes a partitioned database table different when adding an index?",
           "partition", "'partitioned database table' vs 'partitioned parent'"),
    QAPair("what prevents a confidential client entry from being read by the wrong agent?",
           "access-ring filter", "'confidential client entry' vs 'Ring 2'"),
    QAPair("what is the correct way to check if an environment variable flag is disabled?",
           "not in ('', '0', 'false', 'no')", "'disabled' vs 'False'"),
    QAPair("how does the system catch a work item that claimed to be done but wasn't?",
           "silent partial compliance", "'claimed to be done' vs 'REVIEW_READY'"),
    QAPair("what gates must a new library pass before it can run in production?",
           "detonation", "'gates' vs 'pipeline', 'library' vs 'package'"),
    QAPair("what table tracks the lifecycle state of an AI-generated idea before it becomes work?",
           "PROPOSED", "'AI-generated idea' vs 'work item'"),
    QAPair("how does the memory extractor avoid processing the same messages twice?",
           "UUID cursor", "'processing the same messages twice' vs 'cursor'"),
    QAPair("what must a subprocess do to ensure its JSON output reaches the caller?",
           "sys.stdout.write", "'JSON output reaches caller' vs 'stdout'"),
    QAPair("how does the system keep track of every Python package and its security check?",
           "bill-of-materials", "'keep track' vs 'SBOM'"),
    QAPair("what happens to a work item that gets stuck with no progress for 30 minutes?",
           "Ghost jobs", "'stuck with no progress' vs 'no heartbeat'"),
    QAPair("how does the proposal engine find functions that are never called?",
           "zero inbound call edges", "'functions never called' vs 'dead code'"),
    QAPair("what prevents the scheduler from hanging when the network storage goes offline?",
           "background thread", "'network storage offline' vs 'stale NFS handle'"),
    QAPair("how should a privileged system command be run without giving the operator sudo?",
           "one-time token", "'privileged command', 'without sudo'"),
    QAPair("what runs code in an isolated environment to check for malicious network activity?",
           "network sinkhole", "'isolated environment' vs 'sandbox'"),
    QAPair("what should an agent capture to long-term memory after completing a work item?",
           "work-item outcomes", "'capture to long-term memory' + 'after completing'"),
    QAPair("when can two models be loaded at the same time without overflowing GPU memory?",
           "lock", "'two models at same time', 'overflowing GPU' vs 'exceed ceiling'"),
    QAPair("what is the order that models are tried before falling back to the cloud API?",
           "32b → 8b → API", "'order' + 'falling back to cloud' vs 'tier batching'"),
    QAPair("how does the system detect when a deliverable was silently skipped?",
           "silent partial compliance", "maps to spec_deviation_disclosure entry"),
    QAPair("what is the minimum set of confirmations required before a high-risk action runs?",
           "approval bridge", "'minimum confirmations' vs 'dual confirmation'"),
]

assert len(ENTRIES) == 30, f"Expected 30 corpus entries, got {len(ENTRIES)}"
assert len(QA_PAIRS) == 30, f"Expected 30 QA pairs, got {len(QA_PAIRS)}"
