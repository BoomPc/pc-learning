"""No network: concurrency and job-wide accounting invariants."""
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from math_agent.parallel_budget import (
    ParallelBudget, CallsExhausted, DeadlineExpired, BudgetCancelled,
)


def test_serial_source_parallel_children_and_review_share_one_limit():
    budget = ParallelBudget(4)
    with budget.request('source') as call:
        assert call.call_id == 1
    barrier = threading.Barrier(2)
    def child(stage):
        with budget.request(stage) as call:
            barrier.wait(timeout=2)
            return call.call_id
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(child, stage) for stage in ('solve:Q1', 'solve:Q2')]
        assert {future.result(timeout=3) for future in futures} == {2, 3}
    with budget.request('review') as call:
        assert call.call_id == 4
    with pytest.raises(CallsExhausted):
        with budget.request('repair'):
            pytest.fail('Budget exhaustion admitted a fifth model call')
    assert budget.calls == 4 and budget.remaining_calls == 0


def test_only_two_active_and_waiter_does_not_consume_budget():
    budget = ParallelBudget(3)
    entered = threading.Barrier(3)
    release = threading.Event()
    waiting = threading.Event()
    third_entered = threading.Event()
    def worker(stage):
        with budget.request(stage):
            entered.wait(timeout=3)
            assert release.wait(timeout=3)
    def third():
        waiting.set()
        with budget.request('third'):
            third_entered.set()
    with ThreadPoolExecutor(max_workers=3) as pool:
        first = [pool.submit(worker, stage) for stage in ('a', 'b')]
        entered.wait(timeout=3)
        last = pool.submit(third)
        assert waiting.wait(timeout=1)
        assert not third_entered.wait(timeout=.03)
        assert budget.snapshot()['active'] == 2 and budget.calls == 2
        release.set()
        for future in first + [last]:
            future.result(timeout=3)
    assert budget.calls == 3 and budget.snapshot()['active'] == 0
    assert budget.snapshot()['peak_concurrency'] == 2


@pytest.mark.parametrize('error', [RuntimeError('network'), KeyboardInterrupt()])
def test_failure_never_refunds_and_releases_slot_even_on_baseexception(error):
    budget = ParallelBudget(2, max_concurrency=1)
    with pytest.raises(type(error)):
        with budget.request('failed'):
            raise error
    with budget.request('next') as call:
        assert call.call_id == 2
    with pytest.raises(CallsExhausted):
        with budget.request():
            pass
    assert budget.snapshot()['records'][0]['failed'] is True


def test_deadline_is_job_wide_not_reset_for_each_branch():
    now = [100.0]
    budget = ParallelBudget(5, timeout_seconds=10, clock=lambda: now[0])
    now[0] = 105.0
    with budget.request('source') as call:
        assert call.remaining_seconds() == 5
    now[0] = 109.0
    with budget.request('solve') as call:
        assert call.remaining_seconds() == 1
        now[0] = 110.0
        with pytest.raises(DeadlineExpired):
            call.check()
    with pytest.raises(DeadlineExpired):
        with budget.request('review'):
            pass
    assert budget.calls == 2


def test_waiting_slot_honors_actual_deadline_without_another_slot_release():
    budget = ParallelBudget(3, timeout_seconds=.06, max_concurrency=1)
    with budget.request('active'):
        with ThreadPoolExecutor(max_workers=1) as pool:
            def wait():
                with budget.request('waiting'):
                    pytest.fail('Expired waiter admitted')
            future = pool.submit(wait)
            with pytest.raises(DeadlineExpired):
                future.result(timeout=1)
        assert budget.calls == 1


def test_cancel_wakes_waiters_and_disallows_new_calls():
    budget = ParallelBudget(3, max_concurrency=1)
    waiting = threading.Event()
    with budget.request('active') as active:
        with ThreadPoolExecutor(max_workers=1) as pool:
            def wait():
                waiting.set()
                with budget.request('waiting'):
                    pytest.fail('Cancelled waiter admitted')
            future = pool.submit(wait)
            assert waiting.wait(timeout=1)
            budget.cancel('fatal branch failure')
            with pytest.raises(BudgetCancelled, match='fatal branch'):
                future.result(timeout=1)
        with pytest.raises(BudgetCancelled):
            active.check()
    with pytest.raises(BudgetCancelled):
        with budget.request('review'):
            pass
    assert budget.calls == 1 and budget.snapshot()['active'] == 0


def test_usage_reports_unknown_requests_instead_of_claiming_zero_cost():
    budget = ParallelBudget(4)
    with budget.request('chat') as call:
        usage = {'prompt_tokens': 20, 'completion_tokens': 40,
                 'completion_tokens_details': {'reasoning_tokens': 35}}
        call.record_usage(usage)
        usage['completion_tokens'] = 999
    with budget.request('responses') as call:
        call.record_usage({'input_tokens': 10, 'output_tokens': 30})
    with budget.request('no_usage'):
        pass
    with budget.request('bad_usage') as call:
        call.record_usage({'prompt_tokens': True, 'completion_tokens': 30})
    assert budget.snapshot()['usage'] == {
        'reported_calls': 2, 'unknown_calls': 2, 'complete': False,
        'not_sent_calls':0,
        'known_prompt_tokens': 30, 'known_completion_tokens': 70,
    }
    snapshot = budget.snapshot()
    snapshot['records'][0]['usage']['prompt_tokens'] = 999
    assert budget.snapshot()['usage']['known_prompt_tokens'] == 30


def test_duplicate_or_closed_usage_cannot_inflate_aggregation():
    budget = ParallelBudget(1)
    with budget.request() as call:
        call.record_usage({'input_tokens': 1, 'output_tokens': 2})
        with pytest.raises(RuntimeError, match='already recorded'):
            call.record_usage({'input_tokens': 10, 'output_tokens': 20})
    with pytest.raises(RuntimeError, match='closed'):
        call.record_usage(None)
    with pytest.raises(RuntimeError, match='closed'):
        call.check()
    assert budget.snapshot()['usage']['known_completion_tokens'] == 2


@pytest.mark.parametrize('kwargs', [
    {'max_calls': 0}, {'max_calls': True}, {'max_calls': 2, 'max_concurrency': 3},
    {'max_calls': 2, 'timeout_seconds': 0}, {'max_calls': 2, 'timeout_seconds': float('nan')},
    {'max_calls': 2, 'deadline': float('inf')},
    {'max_calls': 2, 'deadline': 10, 'timeout_seconds': 1},
])
def test_invalid_budget_configuration_rejected(kwargs):
    with pytest.raises(ValueError):
        ParallelBudget(**kwargs)


def test_unlimited_deadline_keeps_output_budget_untouched():
    budget = ParallelBudget(1)
    with budget.request() as call:
        assert call.remaining_seconds() is None
    assert budget.snapshot()['remaining_seconds'] is None


def test_public_check_guards_dispatch_merge_and_publication_without_reserving():
    now = [10.0]
    budget = ParallelBudget(1, deadline=20.0, clock=lambda: now[0])
    budget.check()
    assert budget.calls == 0
    with budget.request('last_call'):
        pass
    budget.check()  # Exhausted calls do not forbid a completed result publication.
    assert budget.calls == 1
    now[0] = 20.0
    with pytest.raises(DeadlineExpired):
        budget.check()
    assert budget.calls == 1


def test_public_check_rejects_cancelled_job():
    budget = ParallelBudget(1)
    budget.cancel('branch failed')
    with pytest.raises(BudgetCancelled, match='branch failed'):
        budget.check()
    assert budget.calls == 0


@pytest.mark.parametrize('concurrency', [1, 2])
def test_peak_concurrency_measures_overlapping_leases_not_configured_limit(concurrency):
    budget = ParallelBudget(4, max_concurrency=concurrency)
    assert budget.snapshot()['peak_concurrency'] == 0
    barrier = threading.Barrier(concurrency)
    def call():
        with budget.request('solve'):
            barrier.wait(timeout=2)
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(call) for _ in range(concurrency)]
        for future in futures:
            future.result(timeout=3)
    assert budget.snapshot()['active'] == 0
    assert budget.snapshot()['peak_concurrency'] == concurrency
    with budget.request('review'):
        pass
    assert budget.snapshot()['peak_concurrency'] == concurrency


def test_serial_actual_work_reports_one_even_if_configured_for_two():
    budget = ParallelBudget(2, max_concurrency=2)
    for stage in ('source', 'review'):
        with budget.request(stage):
            pass
    assert budget.snapshot()['peak_concurrency'] == 1
