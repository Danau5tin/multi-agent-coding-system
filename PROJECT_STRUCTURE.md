# Project Structure Documentation

## Directory Structure

```
multi-agent-coding-system/
├── src/
│   └── multi_agent_coding_system/     # Main package (restructured as importable package)
│       ├── agents/                     # Agent implementations and coordination
│       │   ├── orchestrator_agent.py        # Stateless orchestrator (fresh messages each turn)
│       │   ├── orchestrator_agent_stateful.py # Stateful orchestrator (accumulating history)
│       │   ├── tbench_orchestrator_agent.py  # Terminal Bench evaluation adapter
│       │   ├── subagent.py                   # Specialized task executors (Explorer/Coder)
│       │   ├── actions/                      # Action handling and parsing
│       │   │   ├── entities/                 # Data models for actions and context
│       │   │   │   ├── actions.py            # 15+ Pydantic action definitions
│       │   │   │   ├── context.py            # Context data model
│       │   │   │   ├── subagent_report.py    # Subagent report structure
│       │   │   │   ├── subagent_result.py    # Processed subagent output (NEW)
│       │   │   │   └── task.py               # Task management models
│       │   │   ├── parsing/                  # Action parsing logic
│       │   │   │   ├── parser.py             # XML-to-action parser
│       │   │   │   └── action_handler.py     # Action execution dispatcher
│       │   │   ├── orchestrator_hub.py       # Central task & context coordination
│       │   │   ├── hierarchical_task_manager.py # Hierarchical task tracking (NEW)
│       │   │   ├── task_manager_base.py      # Abstract task manager interface (NEW)
│       │   │   ├── file_manager.py           # File operations (read/write/edit)
│       │   │   ├── search_manager.py         # Search operations (grep/glob/ls)
│       │   │   └── state_managers.py         # Todo and scratchpad management
│       │   ├── env_interaction/              # Environment interaction layer
│       │   │   ├── command_executor.py       # Docker/command execution
│       │   │   ├── env_info_retriever.py     # Environment context collection (NEW)
│       │   │   ├── turn_executor.py          # Single-turn execution orchestration
│       │   │   └── entities/                 # Execution-related models
│       │   │       ├── conversation_history.py
│       │   │       ├── execution_result.py
│       │   │       └── turn.py
│       │   ├── state/                        # State management
│       │   │   └── orchestrator_state.py     # Orchestrator state serialization
│       │   ├── system_msgs/                  # System messages for agents
│       │   │   ├── system_msg_loader.py      # Message loading with caching
│       │   │   └── md_files/                 # Markdown system messages
│       │   │       ├── orchestrator_sys_msg.md # Orchestrator instructions
│       │   │       ├── explorer_sys_msg.md     # Explorer subagent instructions
│       │   │       └── coder_sys_msg.md        # Coder subagent instructions
│       │   └── utils/                        # Utilities
│       │       ├── llm_client.py             # LiteLLM client with retry logic (ENHANCED)
│       │       ├── critical_error_logger.py  # Async error logging to disk (NEW)
│       │       └── time_utils.py             # Elapsed time formatting (NEW)
│       └── misc/                             # Miscellaneous utilities
│           ├── log_setup.py                  # Dual-handler logging configuration
│           ├── session_logger.py             # Structured JSON execution logging (NEW)
│           └── async_docker_container_manager.py # Multi-node container orchestration (NEW)
├── evaluation/                          # Terminal Bench evaluation framework (NEW)
│   ├── docs/
│   │   ├── deploying_model_examples.md      # SGLang/vLLM deployment guides
│   │   ├── running_tbench_evals.md          # Evaluation setup instructions
│   │   └── model_mixing_tbench_evals/       # Model combination experiments
│   │       ├── orca_model_mix_tbench_results.md # Results summary
│   │       └── results/                      # 40+ JSON result files
│   └── run_terminal_bench_eval.sh           # Main evaluation script
├── tests/                               # Test suite
│   ├── test_action_parser.py           # Action parsing unit tests (13+ tests)
│   ├── test_hierarchical_task_manager.py # Task hierarchy tests (22+ tests) (NEW)
│   ├── test_efficiency_tracker.py      # Performance tracking tests (NEW)
│   ├── test_async_docker_manager.py    # Single-node Docker tests (NEW)
│   ├── test_multi_node_docker_manager.py # Multi-node Docker tests (NEW)
│   ├── test_orchestrator_real.py       # Orchestrator integration tests (NEW)
│   ├── test_subagent_real.py           # Subagent integration tests
│   └── test_assets/                    # Test resources
│       └── dockerfile_with_heredoc
├── readme_imgs/                         # Documentation images (NEW)
│   ├── orch_agent_sys_arch.png
│   ├── orchestrator-qwen-3-coder-stanford-terminal-bench-leaderboard.png
│   ├── orchestrator-sonnet-4-stanford-terminal-bench-leaderboard.png
│   └── perf_chart.png
├── new_features.md                      # v0.1 release notes (NEW)
├── LICENSE.md                           # License information (NEW)
├── pyproject.toml                       # Project dependencies and metadata
└── README.md                            # Project overview
```

## Core Components

### 1. **OrchestratorAgent** (`src/multi_agent_coding_system/agents/orchestrator_agent.py`)
Stateless orchestrator that coordinates multi-agent task execution with fresh message context each turn.

**Key Responsibilities:**
- Receives high-level task instructions and manages execution lifecycle
- Coordinates task creation and subagent delegation via OrchestratorHub
- Tracks token usage for billing (messages retained only for counting)
- Monitors elapsed time and enforces execution constraints
- Maintains state via OrchestratorState (tasks, contexts, conversation history)

**Key Methods:**
- `setup()`: Initializes task manager, orchestrator hub, action handler, turn executor, state
- `execute_turn(instruction, turn_num)`: Single turn with fresh user message containing full state
- `run(instruction, max_turns)`: Main execution loop until FinishAction or max turns
- `_get_llm_response(user_message)`: Calls LiteLLM client with system + user messages

**Design Pattern:** Stateless per-turn execution - only tracks messages for token counting, not full conversation history

### 1.1 **OrchestratorAgentStateful** (`src/multi_agent_coding_system/agents/orchestrator_agent_stateful.py`)
Stateful variant that accumulates full message history across all turns (RL training style).

**Key Differences from OrchestratorAgent:**
- `messages: List[Dict[str, str]]` - Maintains complete message history
- `execute_turn()` - Simpler signature, uses accumulated state
- `_get_llm_response()` - Uses full accumulated messages directly
- `run()` - Initializes messages with system + environment context, then accumulates all turns

**Use Case:** Reinforcement learning training where model needs to see full trajectory

### 1.2 **TBenchOrchestratorAgent** (`src/multi_agent_coding_system/agents/tbench_orchestrator_agent.py`)
Terminal Bench evaluation adapter wrapping OrchestratorAgent for Stanford's benchmark framework.

**Key Responsibilities:**
- Implements BaseAgent interface for Terminal Bench compatibility
- Extracts container name from TmuxSession
- Creates DockerExecutor and runs orchestrator in async event loop
- Aggregates token counts from orchestrator + all subagents
- Returns AgentResult with token metrics and failure mode

**Variants:**
- `TBenchOrchestratorAgent(OrchestratorAgent, BaseAgent)` - Stateless wrapper
- `TBenchOrchestratorAgentStateful(OrchestratorAgentStateful, BaseAgent)` - Stateful wrapper

### 2. **Subagent** (`src/multi_agent_coding_system/agents/subagent.py`)
Specialized agents that execute delegated tasks autonomously and report results back to orchestrator.

**Agent Types:**
- **Explorer Agent**: Investigates codebase, searches for information, gathers context
- **Coder Agent**: Implements features, fixes bugs, writes code, performs file operations

**Key Responsibilities:**
- Load type-specific system message (explorer vs coder)
- Execute tasks within defined scope using available actions
- Collect and report contexts discovered during execution
- Handle parsing errors and enforce completion via forced reporting
- Track token usage and execution metrics
- Truncate environment responses to prevent context overflow (~12k chars)

**Key Methods:**
- `__init__()`: Initializes with SubagentTask, executor, LLM config, logging, time constraints
- `run()`: Main execution loop (up to max_turns) until ReportAction submitted
- `_build_task_prompt()`: Constructs initial prompt with task details, contexts, bootstrap files
- `_force_report()`: Forces agent to submit report when stuck (parsing errors, timeout, max turns)
- `_truncate_env_response()`: Prevents inference server overload by limiting response size
- `_check_for_report()`: Extracts SubagentReport from actions

**Advanced Features:**
- **Forced Reporting**: Automatic report generation after N consecutive parsing errors (default 3)
- **Response Truncation**: Limits environment responses to ~3k tokens to prevent context overflow
- **Timeout Protection**: Forces report if execution time exceeds max_execution_time_seconds
- **Context Window Handling**: Gracefully handles ContextWindowExceededError
- **Session Logging**: Optional detailed turn-by-turn logging for debugging

**Execution Flow:**
1. Load system message based on agent_type
2. Build task prompt with title, description, provided contexts, bootstrap files
3. Get initial environment state (pwd, file tree, README, etc.)
4. For each turn (up to max_turns):
   - Get LLM response with accumulated message history
   - Execute actions via action handler
   - Check for parsing errors / no actions - force report if threshold reached
   - Check for ReportAction - return SubagentReport if found
   - Truncate environment responses
5. Force report at max turns with progress summary

### 3. **OrchestratorHub** (`src/multi_agent_coding_system/agents/actions/orchestrator_hub.py`)
Central coordination hub managing hierarchical tasks and shared context storage.

**Core Responsibilities:**
- **Hierarchical Task Management**: Create/update/query tasks via HierarchicalTaskManager
- **Context Store**: Centralized storage for discovered information with ID-based retrieval
- **Context Reference Resolution**: Resolve context_refs (direct ID or task ID) to actual content
- **Subagent Result Processing**: Extract contexts from SubagentReport and store in context_store

**Key Methods:**
- `create_task()`: Create root task (depth 0) via task manager
- `create_subtask(parent_id)`: Create child task (depth = parent.depth + 1)
- `update_task_status(task_id, status, error_message)`: Update task state
- `view_all_tasks()`: Formatted hierarchical task tree for display
- `add_context(context_id, content, reported_by, task_id)`: Add context to store
- `get_contexts_for_task(context_refs)`: Resolve references to Dict[id -> content]
- `validate_context_refs(context_refs)`: Validate references before task creation
- `view_context_store()`: Formatted context store summary
- `process_subagent_result(task_id, report, verbose)`: Extract and store contexts from report

**Context Reference Resolution:**
- Direct references: `context_id` -> looks up in context_store
- Task ID references: `task_XXX` -> gets all contexts reported by that task
- Suffix handling: `task_XXX_output` -> removes `_output` suffix

**Data Flow:**
1. Orchestrator creates tasks with context_refs via TaskCreateAction
2. Hub validates context_refs before task creation
3. Subagent executes task and returns SubagentReport with contexts
4. Hub processes report via `process_subagent_result()`:
   - Extracts contexts from report
   - Stores in context_store with task_id association
   - Creates SubagentResult (or VerboseSubagentResult)
   - Updates task status to COMPLETED
5. Future tasks can reference stored contexts by ID or task ID

### 4. **Action System** (`src/multi_agent_coding_system/agents/actions/`)
Comprehensive action framework enabling agent-environment interaction through structured XML/YAML commands.

**Action Categories (15+ action types):**

**Execution:**
- `BashAction`: Execute bash commands (cmd, block, timeout_secs)
- `FinishAction`: Mark task as complete (message)

**Todo Management:**
- `TodoOperation`: Single operation (action: add/complete/delete/view_all, content, task_id)
- `BatchTodoAction`: Multiple todo operations (operations[], view_all flag)

**File Operations:**
- `ReadAction`: Read file with optional line range (file_path, offset, limit)
- `WriteAction`: Write file with directory creation (file_path, content)
- `EditAction`: String replacement (file_path, old_string, new_string, replace_all)
- `MultiEditAction`: Multiple edits on same file (file_path, edits[])
- `FileMetadataAction`: Get file stats (file_paths[])
- `WriteTempScriptAction`: Write temporary script (file_path, content)

**Search Operations:**
- `GrepAction`: Regex search (pattern, path, include)
- `GlobAction`: Find files by pattern (pattern, path)
- `LSAction`: List directory (path, ignore[])

**Scratchpad:**
- `AddNoteAction`: Add note (content)
- `ViewAllNotesAction`: View all notes

**Task Management:**
- `TaskCreateAction`: Create task (agent_type, title, description, context_refs[], context_bootstrap[], auto_launch)
- `AddContextAction`: Add context to store (id, content, reported_by, task_id)
- `LaunchSubagentAction`: Launch subagent (task_id)
- `ReportAction`: Report results (contexts[], comments)

**Parser Pipeline:**
1. **XML Extraction**: Extract `<tag>content</tag>` pairs from LLM response
2. **Tag Mapping**: Map tag names to Action classes (file/read, search/grep, etc.)
3. **YAML Parsing**: Parse content as YAML (or plain string for finish)
4. **Pydantic Validation**: Validate via Action.model_validate()
5. **Execution**: Route to ActionHandler for execution

**Design Pattern:** Declarative action definitions using Pydantic models with automatic YAML validation

### 5. **Hierarchical Task Manager** (`src/multi_agent_coding_system/agents/actions/hierarchical_task_manager.py`)
Manages hierarchical task relationships with ownership control and depth limits.

**Key Responsibilities:**
- Create parent-child task relationships with depth tracking
- Enforce ownership-based access control (agents own their tasks)
- Track task status with recursive aggregation
- Provide formatted tree visualization
- Thread-safe concurrent task operations

**Key Methods:**
- `create_task()`: Create root task (depth 0)
- `create_subtask(parent_id)`: Create child task (depth = parent.depth + 1)
- `update_status(task_id, status, owner_id)`: Update task (owner-locked)
- `get_tree(root_id)`: Hierarchical tree representation
- `get_aggregated_status(task_id)`: Recursive status from children
- `format_tree_display()`: Formatted text tree for LLM prompts

**Task Hierarchy:**
- **Max Depth**: 2 (Orchestrator -> Subagent -> Sub-subagent)
- **Ownership**: Agents can only modify their own tasks
- **Status Lifecycle**: CREATED -> COMPLETED/FAILED
- **Aggregation Rules**:
  - Leaf tasks: return their own status
  - Parent with unfinished children: CREATED
  - Parent with all children completed: COMPLETED

**Design Pattern:** Hierarchical state machine with ownership-based access control and depth limiting

### 6. **Execution Layer** (`src/multi_agent_coding_system/agents/env_interaction/`)
Handles action execution, environment interaction, and Docker container operations.

**Components:**

**6.1 TurnExecutor** (`turn_executor.py`):
- Coordinates action parsing and execution for a single turn
- `execute(llm_output)`: Parses actions, executes via ActionHandler, returns ExecutionResult
- Handles no-action case, parsing errors, and FinishAction detection
- Collects subagent trajectories and context statistics

**6.2 CommandExecutor** (`command_executor.py`):
- Abstract base class with DockerExecutor implementation
- `execute(cmd, timeout)`: Execute command in Docker, return (output, exit_code)
- `execute_background(cmd)`: Fire-and-forget background execution
- Supports AsyncDockerContainerManager (multi-node) and subprocess (single Docker daemon)
- Combines stdout/stderr with timeout handling

**6.3 EnvInfoRetriever** (`env_info_retriever.py`):
- Runs startup commands to provide environment context snapshot
- Commands: pwd, Python/pip versions, file extensions stats, directory tree, README, requirements.txt, processes, disk space, environment variables
- Returns formatted markdown with code blocks

**6.4 ExecutionResult** (`entities/execution_result.py`):
- Dataclass representing single-turn execution result
- Attributes: actions_executed, env_responses, has_error, has_parsing_error, done, finish_message, subagent_trajectories, context stats
- Methods: to_dict(), to_user_msg_content()

**6.5 Turn** (`entities/turn.py`):
- Represents single conversation turn
- Attributes: llm_output, actions_executed, env_responses, subagent_trajectories
- Methods: to_dict(), to_prompt()

**6.6 ConversationHistory** (`entities/conversation_history.py`):
- Maintains orchestrator conversation history
- Methods: add_turn(), to_dict(), to_prompt()

## Key Architecture Patterns

### 1. **Dual Orchestrator Modes Pattern**
The system supports two execution modes for different use cases:
- **Stateless (OrchestratorAgent)**: Fresh messages each turn, state injected via user message. Optimal for inference with efficient token usage.
- **Stateful (OrchestratorAgentStateful)**: Accumulates full message history across all turns. Used for RL training where model needs to see full trajectory.

**Trade-offs:**
- Stateless: Lower token costs, requires state serialization in prompts
- Stateful: Higher token costs, simpler implementation, better for training rollouts

### 2. **Hierarchical Multi-Agent Orchestration Pattern**
The system employs a hierarchical multi-agent architecture:
- **Orchestrator** (depth 0): Top-level task decomposition and coordination
- **Subagents** (depth 1): Specialized workers (Explorer/Coder) for delegated tasks
- **Sub-subagents** (depth 2, if needed): Further decomposition with max depth enforcement
- **Communication**: Structured SubagentReports with contexts and comments
- **Context Sharing**: Centralized context store enables knowledge sharing across agent boundaries

**Hierarchy Properties:**
- Max depth = 2 (prevents infinite recursion)
- Ownership-based access control (agents own their tasks)
- Status aggregation from children to parents

### 3. **Context Store Pattern**
Centralized information management with flexible reference resolution:
- Subagents discover and report contexts via ReportAction
- Orchestrator Hub stores contexts with unique IDs and task associations
- **Reference Types**:
  - Direct references: `context_id` -> specific context
  - Task ID references: `task_XXX` -> all contexts from that task
- Validation before task creation ensures all references are resolvable
- Enables knowledge sharing and context reuse across tasks

### 4. **Action-First Design**
All agent capabilities are expressed as discrete, validated actions:
- **Declarative Definitions**: 15+ Pydantic action models with Field() constraints
- **XML/YAML Syntax**: LLM outputs XML tags with YAML content
- **Validation Pipeline**: XML extraction -> YAML parsing -> Pydantic validation -> execution
- **Separation of Concerns**: Parser (SimpleActionParser) separate from executor (ActionHandler)
- **Extensibility**: Add new actions by defining Pydantic model and handler method

### 5. **Forced Completion Pattern**
Ensures task termination and prevents stuck agents:
- **Max Turn Limits**: Both orchestrator and subagents have configurable max_turns
- **Parsing Error Tracking**: Force report after N consecutive parsing errors (default 3)
- **No-Action Tracking**: Force report after N consecutive turns with no actions
- **Timeout Protection**: Force report if execution time exceeds max_execution_time_seconds
- **Fallback Report Generation**: System generates report with diagnostic information
- **Context Window Handling**: Gracefully handles ContextWindowExceededError

### 6. **Response Truncation Pattern**
Prevents context overflow and inference server overload:
- Subagents truncate environment responses to ~12k chars (~3k tokens)
- Truncation applied after action execution, before adding to messages
- Prevents cascading context window issues in long-running tasks
- Maintains conversation continuity while respecting model limits

### 7. **Token Tracking Architecture**
Comprehensive token usage monitoring for cost management:
- Each agent tracks input/output tokens via centralized LLM client
- Orchestrator aggregates tokens from all subagent executions
- Terminal Bench adapter provides token counts in AgentResult
- Supports both LiteLLM token_counter and model-specific counting

### 8. **Error Resilience Pattern**
Multiple layers of error handling across the system:
- **Parsing Errors**: Collected and reported to agent, execution continues if some actions succeed
- **Execution Errors**: Captured with full stack traces, returned as environment responses
- **Critical Errors**: Logged to disk asynchronously for debugging
- **Retry Logic**: LLM client retries on InternalServerError and overloaded_error with exponential backoff (max 10 retries)
- **Continuation Strategies**: Agents can recover from errors and continue execution

### 9. **Dependency Injection Pattern**
Components are loosely coupled for testability and flexibility:
- CommandExecutor injected into agents (supports Docker, mock, etc.)
- Shared executor across orchestrator and subagents
- OrchestratorHub passed to ActionHandler for context/task operations
- Configurable LLM clients with model, temperature, API key overrides
- SessionLogger optional (can be None for lightweight execution)

### 10. **Async-First Design**
Full async/await support for high-concurrency scenarios:
- All I/O operations (LLM calls, Docker commands, file operations) are async
- Supports parallel subagent execution (N subagents in parallel)
- AsyncDockerContainerManager enables multi-node distributed containers
- Async locks for thread-safe concurrent operations (task manager, session logger)
- Compatible with asyncio event loops for integration with Terminal Bench

### 11. **Multi-Node Container Orchestration Pattern**
Distributed execution environment with load balancing:
- **AsyncDockerContainerManager**: Manages containers across multiple Docker daemons
- **Endpoint Configuration**: Supports mixed local/remote endpoints (Unix socket, TCP)
- **Load Balancing**: Least-loaded node selection for container placement
- **Error Recovery**: Cache corruption detection, dangling image cleanup, rebuild without cache
- **Scaling**: Enables 256+ concurrent containers for RL training on multi-GPU clusters

### 12. **Structured Session Logging Pattern**
Hierarchical execution tracking for debugging and analysis:
- **SessionLogger**: JSON-formatted execution logs with hierarchical turn structure
- **Subagent Tracking**: SubagentSessionTracker captures individual subagent turns
- **Metadata**: Task descriptions, token counts, execution time, completion reason
- **Incremental Saves**: Writes to file after each turn (crash recovery)
- **Optional**: Can be disabled for lightweight execution (logging_dir=None)

### 13. **System Message Separation Pattern**
Flexible system message management with type-based loading:
- System messages stored as markdown files (orchestrator_sys_msg.md, explorer_sys_msg.md, coder_sys_msg.md)
- Dynamic loading based on agent type and depth
- LRU caching for performance (functools.lru_cache)
- Separation of prompting logic from code enables rapid iteration
- Easy updates without code changes or redeployment

### 14. **Environment Snapshot Pattern**
Agents receive comprehensive environment context on startup:
- EnvInfoRetriever runs startup commands (pwd, file tree, README, package files, processes, etc.)
- Formatted as markdown with code blocks
- Included in initial user message for both orchestrator and subagents
- Reduces need for exploratory actions at task start
- Provides grounding in actual environment state

### 15. **Anthropic Prompt Caching Pattern**
Optimizes token costs for Anthropic models:
- LLM client automatically applies cache_control to Anthropic messages
- Caches system message (unchanged across turns)
- Caches last 2 user messages (likely contains task state)
- Uses ephemeral cache type
- Transparent to agents (applied automatically in get_llm_response())

---

## Evaluation Framework

### Terminal Bench Integration (`evaluation/`)
Comprehensive benchmarking infrastructure for evaluating multi-agent coding system performance.

**Purpose:** Measure task completion rate, token usage, and execution time on Stanford's Terminal Bench benchmark.

**Key Components:**

**1. Evaluation Script** (`run_terminal_bench_eval.sh`):
- Configures orchestrator and subagent models via environment variables
- Sets concurrency level (N_CONCURRENT_TRIALS, default 5)
- Runs Terminal Bench CLI with custom agent import path
- Collects detailed JSON results with token counts and timings

**2. Model Mixing Experiments** (`docs/model_mixing_tbench_evals/`):
- 40+ experiment result files testing different orchestrator/subagent model combinations
- Best performing: Qwen3-30B-A3B + Grok-Fast-1 (23.13% on TBench)
- Tracks stateful vs stateless variants, step counts, stage progression

**3. Deployment Guides** (`docs/deploying_model_examples.md`):
- SGLang serving setup (8x H100 optimal)
- vLLM serving with tensor parallelism
- Multi-node distributed inference with Ray cluster
- Network configuration for cross-node communication

**Environment Variables:**
- `ORCA_ORCHESTRATOR_MODEL`: Orchestrator LLM model
- `ORCA_SUBAGENT_MODEL`: Subagent LLM model
- `N_CONCURRENT_TRIALS`: Parallel task execution count
- `N_ATTEMPTS`: Attempts per task (TBench requirement: 5)
- `ENABLE_TOKEN_COUNTING`: Track token usage
- `USE_STATEFUL`: Toggle stateful/stateless orchestrator

**Metrics Tracked:**
- Task completion rate (%)
- Token usage (input/output)
- Execution time per task
- Number of turns/attempts
- Failure modes

---

## Utility Infrastructure

### 7. **AsyncDockerContainerManager** (`src/multi_agent_coding_system/misc/async_docker_container_manager.py`)
Multi-node Docker container orchestration with load balancing and error recovery.

**Key Capabilities:**
- **Multi-Node Support**: Manages containers across multiple Docker daemons (local Unix socket or remote TCP)
- **Load Balancing**: Least-loaded node selection algorithm for container placement
- **Container Lifecycle**: Build from Dockerfile, start, execute commands, copy files, cleanup
- **Error Recovery**: Cache corruption detection, dangling image cleanup, rebuild without cache
- **Async Operations**: Full async/await support for high-concurrency scenarios

**Key Methods:**
- `spin_up_container_from_dir()`: Build image and start container
- `execute_command(container_id, cmd, timeout)`: Run bash commands in container
- `copy_file_to_container()`: Copy files via tar archives
- `close_container()`: Stop and remove container
- `cleanup_all()`: Stop all managed containers

**Configuration:**
- `DOCKER_ENDPOINTS` environment variable (comma-separated list)
- Default: `unix:///var/run/docker.sock`
- Example: `["unix:///var/run/docker.sock", "tcp://10.15.25.9:2375"]`

**Use Cases:**
- Single-node development and testing
- Multi-node RL training (256+ concurrent containers on 32 H100s)
- Distributed evaluation runs

### 8. **SessionLogger** (`src/multi_agent_coding_system/misc/session_logger.py`)
Hierarchical execution tracking with structured JSON output for debugging and analysis.

**Architecture:**
```
Session
├── metadata (task, session_id, agent_type)
├── turns: List[Turn]
│   ├── turn_number, timestamp
│   ├── llm_output, env_response, actions
│   └── subagent_sessions: List[SubagentSession]
│       ├── agent_id, agent_type, task_title
│       ├── turns: List[Dict] (individual subagent turns)
│       ├── report, token counts
│       └── start_time, end_time
```

**Key Methods:**
- `start_session(task, metadata)`: Initialize session
- `start_turn(turn_number)`: Begin new turn
- `update_turn(llm_output, env_response, actions)`: Update current turn
- `add_subagent_session(session)`: Add completed subagent session
- `end_turn()`: Finalize turn and save to file
- `end_session(reason)`: Complete session

**Features:**
- **Incremental Saves**: Writes to file after each turn (crash recovery)
- **Hierarchical Structure**: Captures orchestrator -> subagent relationships
- **Token Tracking**: Records input/output tokens per agent
- **Async Safe**: Uses asyncio.Lock for concurrent write safety
- **Optional**: Can be disabled (logging_dir=None)

**Output:** `{session_id}_session.json` with full execution trace

### 9. **Critical Error Logger** (`src/multi_agent_coding_system/agents/utils/critical_error_logger.py`)
Async error logging to disk for debugging critical system failures.

**Key Features:**
- Writes error reports as JSON with timestamp-based filenames
- Thread-safe with asyncio.Lock
- Singleton pattern via `get_critical_error_logger(output_dir)`
- Captures error type, message, metadata, timestamp

**Use Cases:**
- LLM client fatal errors (after max retries)
- Unexpected system exceptions
- Debugging production issues

### 10. **LLM Client** (`src/multi_agent_coding_system/agents/utils/llm_client.py`)
Centralized LiteLLM interface with retry logic and Anthropic caching.

**Key Functions:**
- `get_llm_response()`: Main async LLM call with retry logic
- `count_input_tokens()`: Token counting using LiteLLM token_counter
- `count_output_tokens()`: Output token counting
- `_apply_anthropic_caching_if_possible()`: Automatic cache_control for Anthropic models

**Retry Strategy:**
- Exponential backoff: 1, 2, 4, 8, 16, 32, 64 seconds (capped at 60s)
- Jitter: up to 10% of base delay
- Max 10 retry attempts
- Retries on InternalServerError and overloaded_error
- Logs fatal errors to disk after max retries

**Anthropic Caching:**
- Marks system message with cache_control
- Marks last 2 user messages with cache_control
- Uses ephemeral cache type
- Transparent to callers

### 11. **Logging Setup** (`src/multi_agent_coding_system/misc/log_setup.py`)
Dual-handler logging configuration with file and console output.

**Configuration:**
- **File Handler**: Detailed format with filename:line number (logs/orchestrator_TIMESTAMP.log)
- **Console Handler**: Simpler format for user visibility (INFO level)
- **Third-Party Suppression**: Sets LiteLLM, OpenAI, httpx, urllib3 to WARNING level

**Usage:**
```python
log_file = setup_file_logging(log_level="DEBUG")
```

---

## Test Suite

### Test Coverage (`tests/`)
7 test files, 62+ test methods, 2,507 lines of code.

**Test Files:**

**1. test_action_parser.py** (540 lines):
- 13+ test methods for XML action parsing
- Covers all 15+ action types
- Tests multiple actions in response, error handling, ignored tags

**2. test_hierarchical_task_manager.py** (468 lines):
- 22+ test methods for task hierarchy operations
- Task creation, subtask creation, depth enforcement
- Owner-based access control, status aggregation
- Concurrent task creation

**3. test_efficiency_tracker.py** (449 lines):
- 17+ async test methods for performance tracking
- Efficiency bonus calculation, benchmark tracking
- Turn-based penalty/reward logic

**4. test_async_docker_manager.py** (350 lines):
- Single-node Docker container tests
- Build, execute, copy files, cleanup

**5. test_multi_node_docker_manager.py** (284 lines):
- Multi-node load balancing tests
- Container distribution verification

**6. test_subagent_real.py** (235 lines):
- End-to-end subagent integration tests
- Real Docker execution with session logging

**7. test_orchestrator_real.py** (181 lines):
- End-to-end orchestrator integration tests
- Full task execution with verification

**Testing Approach:**
- **Unit Tests**: Isolated component testing with mocks
- **Integration Tests**: Real Docker containers and command execution
- **Async Tests**: pytest-asyncio for concurrent operations
- **Fixtures**: Temporary directories, database fixtures
- **Assertions**: Dataclass equality, collection membership, file content verification

---

## New Features (v0.1)

Based on `new_features.md`, recent enhancements include:

### System Architecture
- **Flexible Model Support**: Orchestrator and subagents can use different models
- **Full Async**: Entire application converted to async patterns
- **Package Structure**: Restructured as importable package

### Orchestrator Enhancements
- **Simplified System Message**: Less instruction-heavy prompts
- **Time Awareness**: Monitors elapsed time and task constraints
- **Environment Snapshots**: Receives system state on startup
- **Context References**: Can reference task IDs to inject contexts

### Subagent Improvements
- **Context Window Handling**: Graceful handling of exceeded context windows
- **Failure Recovery**: Forced reporting after consecutive parsing failures
- **Environment Snapshots**: Receive system state on startup

### Distributed Computing
- **Multi-Node Docker**: AsyncDockerContainerManager with load balancing
- **RL Training Support**: Verifier environments, curriculum learning, rollout management
- **Multi-Node NFS**: Cloud-provider NFS configuration scripts

### Testing & Evaluation
- **Unit Tests**: Pytest integration with result parsing
- **Docker Tests**: Single-node and multi-node container tests
- **Terminal Bench Results**: Model mixing experiment documentation