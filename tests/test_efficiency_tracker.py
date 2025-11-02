"""
Tests for the efficiency bonus reward tracker.

Tests the logic for tracking highest scores and awarding bonuses when
agents achieve the same score in fewer turns.
"""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio

# Import the efficiency tracker module
import sys
# from reward.efficiency_tracker import (
#     check_and_update_efficiency,
#     get_task_benchmark,
#     reset_benchmarks,
#     EFFICIENCY_BONUS_AMOUNT,
#     EFFICIENCY_PENALTY_AMOUNT,
#     EFFICIENCY_PENALTY_THRESHOLD,
#     MIN_TURNS_FOR_PENALTY,
#     MIN_TURNS_TO_RECORD
# )


@pytest_asyncio.fixture
async def temp_benchmarks_db():
    """Create a temporary benchmarks database for testing."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        temp_path = Path(f.name)

    # Patch the BENCHMARKS_DB constant
    with patch('reward.efficiency_tracker.BENCHMARKS_DB', temp_path):
        # Reset benchmarks at start of test
        await reset_benchmarks()
        yield temp_path

    # Cleanup
    if temp_path.exists():
        temp_path.unlink()
    # Clean up WAL files
    wal_file = temp_path.with_suffix('.db-wal')
    if wal_file.exists():
        wal_file.unlink()
    shm_file = temp_path.with_suffix('.db-shm')
    if shm_file.exists():
        shm_file.unlink()


@pytest.mark.asyncio
async def test_first_completion(temp_benchmarks_db):
    """Test that first completion of a task stores benchmark with no bonus."""
    task_name = "test-task-1"
    score = 0.75
    turns = 10

    bonus = await check_and_update_efficiency(task_name, score, turns)

    assert bonus == 0.0, "First completion should not award bonus"

    # Verify benchmark was stored
    benchmark = await get_task_benchmark(task_name)
    assert benchmark['highest_score'] == score
    assert benchmark['best_turns'] == turns


@pytest.mark.asyncio
async def test_efficiency_improvement_gets_bonus(temp_benchmarks_db):
    """Test that matching best score in fewer turns awards bonus."""
    task_name = "test-task-2"
    score = 0.80

    # First completion
    bonus1 = await check_and_update_efficiency(task_name, score, 15)
    assert bonus1 == 0.0, "First completion should not award bonus"

    # Second completion with same score, fewer turns
    bonus2 = await check_and_update_efficiency(task_name, score, 12)
    assert bonus2 == EFFICIENCY_BONUS_AMOUNT, "Should award bonus for efficiency improvement"

    # Verify best_turns was updated
    benchmark = await get_task_benchmark(task_name)
    assert benchmark['best_turns'] == 12


@pytest.mark.asyncio
async def test_same_score_same_turns_no_bonus(temp_benchmarks_db):
    """Test that matching best score with same turns gives no bonus."""
    task_name = "test-task-3"
    score = 0.70
    turns = 10

    # First completion
    await check_and_update_efficiency(task_name, score, turns)

    # Second completion with same score and turns
    bonus = await check_and_update_efficiency(task_name, score, turns)
    assert bonus == 0.0, "Same performance should not award bonus"


@pytest.mark.asyncio
async def test_same_score_more_turns_no_penalty_within_threshold(temp_benchmarks_db):
    """Test that matching best score with slightly more turns (within threshold) gives no penalty."""
    task_name = "test-task-4"
    score = 0.85

    # First completion with MIN_TURNS_FOR_PENALTY or more turns
    await check_and_update_efficiency(task_name, score, 10)

    # Second completion with same score but only +2 turns (within threshold)
    bonus = await check_and_update_efficiency(task_name, score, 12)
    assert bonus == 0.0, "Slightly worse efficiency within threshold should not give penalty"

    # Verify best_turns was NOT updated
    benchmark = await get_task_benchmark(task_name)
    assert benchmark['best_turns'] == 10


@pytest.mark.asyncio
async def test_higher_score_updates_benchmark(temp_benchmarks_db):
    """Test that achieving a higher score updates the benchmark."""
    task_name = "test-task-5"

    # First completion
    await check_and_update_efficiency(task_name, 0.50, 10)

    # Second completion with higher score
    bonus = await check_and_update_efficiency(task_name, 0.90, 15)
    assert bonus == 0.0, "New highest score should not award bonus (first time at this level)"

    # Verify benchmark was updated
    benchmark = await get_task_benchmark(task_name)
    assert benchmark['highest_score'] == 0.90
    assert benchmark['best_turns'] == 15


@pytest.mark.asyncio
async def test_lower_score_no_bonus_regardless_of_turns(temp_benchmarks_db):
    """Test that lower score never gets bonus, even with fewer turns."""
    task_name = "test-task-6"

    # First completion with high score
    await check_and_update_efficiency(task_name, 0.90, 20)

    # Second completion with lower score but very few turns
    bonus = await check_and_update_efficiency(task_name, 0.50, 5)
    assert bonus == 0.0, "Lower score should never award bonus"

    # Verify benchmark was NOT updated
    benchmark = await get_task_benchmark(task_name)
    assert benchmark['highest_score'] == 0.90
    assert benchmark['best_turns'] == 20


@pytest.mark.asyncio
async def test_new_high_score_then_efficiency_improvement(temp_benchmarks_db):
    """Test the full flow: new high score, then efficiency improvement."""
    task_name = "test-task-7"

    # Rollout 1: Initial score
    bonus1 = await check_and_update_efficiency(task_name, 0.60, 12)
    assert bonus1 == 0.0

    # Rollout 2: Same score, fewer turns -> BONUS
    bonus2 = await check_and_update_efficiency(task_name, 0.60, 10)
    assert bonus2 == EFFICIENCY_BONUS_AMOUNT

    # Rollout 3: New highest score
    bonus3 = await check_and_update_efficiency(task_name, 0.95, 18)
    assert bonus3 == 0.0

    # Rollout 4: Match new high score with fewer turns -> BONUS
    bonus4 = await check_and_update_efficiency(task_name, 0.95, 14)
    assert bonus4 == EFFICIENCY_BONUS_AMOUNT

    # Verify final benchmark
    benchmark = await get_task_benchmark(task_name)
    assert benchmark['highest_score'] == 0.95
    assert benchmark['best_turns'] == 14


@pytest.mark.asyncio
async def test_score_rounding(temp_benchmarks_db):
    """Test that scores are rounded correctly for comparison."""
    task_name = "test-task-8"

    # First completion with score that will be rounded
    await check_and_update_efficiency(task_name, 0.7541, 10)

    # Second completion with slightly different score that rounds to same value
    bonus = await check_and_update_efficiency(task_name, 0.7549, 8)
    # Both should round to 0.75 (2 decimal places)
    assert bonus == EFFICIENCY_BONUS_AMOUNT, "Rounded scores should be treated as equal"


@pytest.mark.asyncio
async def test_multiple_tasks_tracked_separately(temp_benchmarks_db):
    """Test that multiple tasks maintain separate benchmarks."""
    task1 = "task-a"
    task2 = "task-b"

    # Task 1 completions
    await check_and_update_efficiency(task1, 0.70, 10)
    bonus1 = await check_and_update_efficiency(task1, 0.70, 8)
    assert bonus1 == EFFICIENCY_BONUS_AMOUNT

    # Task 2 completions (should be independent)
    await check_and_update_efficiency(task2, 0.80, 15)
    bonus2 = await check_and_update_efficiency(task2, 0.80, 12)
    assert bonus2 == EFFICIENCY_BONUS_AMOUNT

    # Verify both benchmarks exist independently
    benchmark1 = await get_task_benchmark(task1)
    benchmark2 = await get_task_benchmark(task2)

    assert benchmark1['highest_score'] == 0.70
    assert benchmark1['best_turns'] == 8
    assert benchmark2['highest_score'] == 0.80
    assert benchmark2['best_turns'] == 12


@pytest.mark.asyncio
async def test_get_benchmark_for_nonexistent_task(temp_benchmarks_db):
    """Test getting benchmark for a task that doesn't exist."""
    benchmark = await get_task_benchmark("nonexistent-task")
    assert benchmark['highest_score'] is None
    assert benchmark['best_turns'] is None


@pytest.mark.asyncio
async def test_efficiency_penalty_for_excessive_turns(temp_benchmarks_db):
    """Test that penalty is applied when exceeding threshold with enough base turns."""
    task_name = "test-task-penalty-1"
    score = 0.80

    # First completion with enough turns to avoid fluke protection
    await check_and_update_efficiency(task_name, score, 5)

    # Second completion with same score but >EFFICIENCY_PENALTY_THRESHOLD extra turns
    # 5 + 3 = 8 turns (3 extra turns > threshold of 2)
    penalty = await check_and_update_efficiency(task_name, score, 8)
    assert penalty == EFFICIENCY_PENALTY_AMOUNT, "Should apply penalty for excessive turns"

    # Verify best_turns was NOT updated
    benchmark = await get_task_benchmark(task_name)
    assert benchmark['best_turns'] == 5


@pytest.mark.asyncio
async def test_no_penalty_when_best_turns_below_min(temp_benchmarks_db):
    """Test that penalty is NOT applied when best_turns < MIN_TURNS_FOR_PENALTY (fluke protection)."""
    task_name = "test-task-penalty-2"
    score = 0.75

    # First completion with very few turns (potential fluke)
    await check_and_update_efficiency(task_name, score, 2)

    # Second completion with same score but many more turns
    # Should NOT apply penalty because best_turns (2) < MIN_TURNS_FOR_PENALTY (3)
    penalty = await check_and_update_efficiency(task_name, score, 10)
    assert penalty == 0.0, "Should not apply penalty when best_turns indicates potential fluke"

    # Verify best_turns was NOT updated
    benchmark = await get_task_benchmark(task_name)
    assert benchmark['best_turns'] == 2


@pytest.mark.asyncio
async def test_zero_score_not_recorded(temp_benchmarks_db):
    """Test that zero scores are not recorded as benchmarks."""
    task_name = "test-task-zero-1"

    # First attempt with zero score
    bonus1 = await check_and_update_efficiency(task_name, 0.0, 10)
    assert bonus1 == 0.0

    # Verify no benchmark was stored
    benchmark = await get_task_benchmark(task_name)
    assert benchmark['highest_score'] is None
    assert benchmark['best_turns'] is None

    # Second attempt with positive score
    bonus2 = await check_and_update_efficiency(task_name, 0.70, 12)
    assert bonus2 == 0.0  # First real completion

    # Verify benchmark was stored this time
    benchmark = await get_task_benchmark(task_name)
    assert benchmark['highest_score'] == 0.70
    assert benchmark['best_turns'] == 12


@pytest.mark.asyncio
async def test_zero_score_no_efficiency_adjustments(temp_benchmarks_db):
    """Test that zero scores never get efficiency bonuses or penalties."""
    task_name = "test-task-zero-2"

    # First completion with positive score
    await check_and_update_efficiency(task_name, 0.80, 10)

    # Failed attempt with zero score and fewer turns
    bonus1 = await check_and_update_efficiency(task_name, 0.0, 5)
    assert bonus1 == 0.0, "Zero score should not get bonus even with fewer turns"

    # Failed attempt with zero score and more turns
    bonus2 = await check_and_update_efficiency(task_name, 0.0, 20)
    assert bonus2 == 0.0, "Zero score should not get penalty even with many more turns"

    # Verify benchmark unchanged
    benchmark = await get_task_benchmark(task_name)
    assert benchmark['highest_score'] == 0.80
    assert benchmark['best_turns'] == 10


@pytest.mark.asyncio
async def test_less_than_min_turns_not_recorded(temp_benchmarks_db):
    """Test that completions with < MIN_TURNS_TO_RECORD are not recorded."""
    task_name = "test-task-min-turns-1"
    score = 0.85

    # First attempt with only 1 turn (< MIN_TURNS_TO_RECORD)
    bonus1 = await check_and_update_efficiency(task_name, score, 1)
    assert bonus1 == 0.0

    # Verify no benchmark was stored
    benchmark = await get_task_benchmark(task_name)
    assert benchmark['highest_score'] is None

    # Second attempt with enough turns
    bonus2 = await check_and_update_efficiency(task_name, score, MIN_TURNS_TO_RECORD)
    assert bonus2 == 0.0  # First recorded completion

    # Verify benchmark was stored this time
    benchmark = await get_task_benchmark(task_name)
    assert benchmark['highest_score'] == score
    assert benchmark['best_turns'] == MIN_TURNS_TO_RECORD


@pytest.mark.asyncio
async def test_less_than_min_turns_no_bonus_even_if_faster(temp_benchmarks_db):
    """Test that completions with < MIN_TURNS_TO_RECORD don't get bonus even if faster."""
    task_name = "test-task-min-turns-2"
    score = 0.90

    # First completion with enough turns
    await check_and_update_efficiency(task_name, score, 5)

    # Second completion with same score in 1 turn (< MIN_TURNS_TO_RECORD)
    # Should NOT get bonus or update benchmark
    bonus = await check_and_update_efficiency(task_name, score, 1)
    assert bonus == 0.0, "Should not award bonus for sub-minimum turn completions"

    # Verify benchmark was NOT updated
    benchmark = await get_task_benchmark(task_name)
    assert benchmark['best_turns'] == 5


@pytest.mark.asyncio
async def test_new_high_score_less_than_min_turns_not_recorded(temp_benchmarks_db):
    """Test that new high scores with < MIN_TURNS_TO_RECORD are not recorded."""
    task_name = "test-task-min-turns-3"

    # First completion
    await check_and_update_efficiency(task_name, 0.70, 5)

    # New high score but with only 1 turn (< MIN_TURNS_TO_RECORD)
    bonus = await check_and_update_efficiency(task_name, 0.95, 1)
    assert bonus == 0.0

    # Verify benchmark was NOT updated to new score
    benchmark = await get_task_benchmark(task_name)
    assert benchmark['highest_score'] == 0.70
    assert benchmark['best_turns'] == 5


if __name__ == "__main__":
    # Run tests manually
    import sys

    async def run_tests():
        """Run all tests manually."""
        print("Running efficiency tracker tests...\n")

        # Create temp database
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            temp_path = Path(f.name)

        try:
            # Patch the benchmarks database path
            with patch('reward.efficiency_tracker.BENCHMARKS_DB', temp_path):
                # Run each test
                tests = [
                    ("First completion", test_first_completion),
                    ("Efficiency improvement gets bonus", test_efficiency_improvement_gets_bonus),
                    ("Same score, same turns - no bonus", test_same_score_same_turns_no_bonus),
                    ("Same score, more turns - no penalty within threshold", test_same_score_more_turns_no_penalty_within_threshold),
                    ("Higher score updates benchmark", test_higher_score_updates_benchmark),
                    ("Lower score no bonus", test_lower_score_no_bonus_regardless_of_turns),
                    ("New high score then efficiency", test_new_high_score_then_efficiency_improvement),
                    ("Score rounding", test_score_rounding),
                    ("Multiple tasks tracked separately", test_multiple_tasks_tracked_separately),
                    ("Get nonexistent task", test_get_benchmark_for_nonexistent_task),
                    ("Efficiency penalty for excessive turns", test_efficiency_penalty_for_excessive_turns),
                    ("No penalty when best turns below min", test_no_penalty_when_best_turns_below_min),
                    ("Zero score not recorded", test_zero_score_not_recorded),
                    ("Zero score no efficiency adjustments", test_zero_score_no_efficiency_adjustments),
                    ("Less than min turns not recorded", test_less_than_min_turns_not_recorded),
                    ("Less than min turns no bonus even if faster", test_less_than_min_turns_no_bonus_even_if_faster),
                    ("New high score less than min turns not recorded", test_new_high_score_less_than_min_turns_not_recorded),
                ]

                passed = 0
                failed = 0

                for name, test_func in tests:
                    try:
                        # Reset database between tests
                        await reset_benchmarks()

                        await test_func(temp_path)
                        print(f"✓ {name}")
                        passed += 1
                    except AssertionError as e:
                        print(f"✗ {name}: {e}")
                        failed += 1
                    except Exception as e:
                        print(f"✗ {name}: Unexpected error: {e}")
                        failed += 1

                print(f"\n{passed} passed, {failed} failed")
                return failed == 0

        finally:
            # Cleanup
            if temp_path.exists():
                temp_path.unlink()
            # Clean up WAL files
            wal_file = temp_path.with_suffix('.db-wal')
            if wal_file.exists():
                wal_file.unlink()
            shm_file = temp_path.with_suffix('.db-shm')
            if shm_file.exists():
                shm_file.unlink()

    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)
