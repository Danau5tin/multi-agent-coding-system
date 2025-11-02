#!/bin/bash

# Default model configuration (fallback if Orca-specific models not set)
export LITELLM_MODEL=${LITELLM_MODEL:-"anthropic/claude-sonnet-4-5-20250929"}
export LITELLM_TEMPERATURE="${LITELLM_TEMPERATURE:-0.1}"
export LITE_LLM_API_KEY="${LITE_LLM_API_KEY}"
export LITE_LLM_API_BASE="${LITE_LLM_API_BASE}"

# Orca-specific model configuration (can override defaults above)
export ORCA_ORCHESTRATOR_MODEL="${ORCA_ORCHESTRATOR_MODEL:-$LITELLM_MODEL}"
export ORCA_ORCHESTRATOR_API_KEY="${ORCA_ORCHESTRATOR_API_KEY:-$LITE_LLM_API_KEY}"
export ORCA_ORCHESTRATOR_API_BASE="${ORCA_ORCHESTRATOR_API_BASE:-$LITE_LLM_API_BASE}"
export ORCA_ORCHESTRATOR_TEMPERATURE="${ORCA_ORCHESTRATOR_TEMPERATURE:-$LITELLM_TEMPERATURE}"

export ORCA_SUBAGENT_MODEL="${ORCA_SUBAGENT_MODEL:-$LITELLM_MODEL}"
export ORCA_SUBAGENT_API_KEY="${ORCA_SUBAGENT_API_KEY:-$LITE_LLM_API_KEY}"
export ORCA_SUBAGENT_API_BASE="${ORCA_SUBAGENT_API_BASE:-$LITE_LLM_API_BASE}"
export ORCA_SUBAGENT_TEMPERATURE="${ORCA_SUBAGENT_TEMPERATURE:-$LITELLM_TEMPERATURE}"


N_CONCURRENT_TRIALS="${N_CONCURRENT_TRIALS:-5}"
N_ATTEMPTS="${N_ATTEMPTS:-5}"

export ENABLE_TOKEN_COUNTING="true"

# Determine which agent to use based on USE_STATEFUL env var
if [ "${USE_STATEFUL}" = "true" ]; then
    AGENT_CLASS="TBenchOrchestratorAgentStateful"
    echo "=========================================="
    echo "Using STATEFUL orchestrator agent 🫙💧"
    echo "=========================================="
else
    AGENT_CLASS="TBenchOrchestratorAgent"
    echo "=========================================="
    echo "Using STATELESS orchestrator agent 🫙"
    echo "=========================================="
fi

uv run tb run \
    -d terminal-bench-core==0.1.1 \
    --agent-import-path src.agents.tbench_orchestrator_agent:${AGENT_CLASS} \
    --n-concurrent-trials "${N_CONCURRENT_TRIALS}" \
    --n-attempts "${N_ATTEMPTS}"

    # --task-id hello-world