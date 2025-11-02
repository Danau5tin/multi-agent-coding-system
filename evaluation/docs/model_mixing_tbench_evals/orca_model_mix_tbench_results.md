# Orcha model mix evaluation results

## Overview

This document notes the findings from trying out different model combinations on TerminalBench.

After playing around with different combinations using the [test files](../../../tests/) and taking into account what seemed to work well, I decided to try:

## TBench details
I ran each combination on the full TerminalBench benchmark using [this script](../../../evaluation/run_terminal_bench_eval.sh) with `N_ATTEMPTS=2|3|5`depending on the run.

## Results

All results output by terminal bench can be found [here](./results/).


| Orca Model | Subagent Model | TBench Score |
|------------|----------------|--------------|
| qwen3-30b-a3b | grok-fast-1 | 23.13% |
| qwen3-14b | sonnet-4.5 | 18.75% |
| Orca-Agent-v0.1 | qwen3-coder-30b-a3b | 18.25% |
| qwen3-30b-a3b | qwen3-coder-480b-a35b | 13.75% |
| qwen3-32b | grok-fast-1 | 16.88% |
| qwen3-32b | qwen3-coder-480b-a35b | 13.75% |
| qwen3-32b | GLM-4.6-FP8 | 13.12% |
| qwen3-14b | grok-fast-1 | 12.92% |
| qwen3-coder-30b-a3b | qwen3-coder-30b-a3b | 12.08% |
| qwen3-32b | qwen3-32b | 8.33% |
| qwen3-14b | qwen3-coder-30b-a3b | 7% |
| qwen3-30b-a3b | qwen3-30b-a3b | 6.25% |