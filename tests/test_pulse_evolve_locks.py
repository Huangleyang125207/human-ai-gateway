# TEST PATTERN: boundary — _EVOLVE_LOCKS 锁身份不漂
# USE WHEN: 验 _get_evolve_lock 多次调同一 target 返同一个 Lock 实例(身份漂 = 静默并发损坏)
# TESTED IN: gateway PULSE refactor P0 TDD net (2026-06-18)
#
# 重构最危险的失败模式:Python 的 Lock 靠**身份**互斥。如果重构后 _get_evolve_lock
# 被多个模块各 import 一次、或重新初始化字典,会导致同 target 返不同 Lock 实例 →
# 测试全绿、并发下数据偷偷损坏。本测守这条:同 target 必返同对象。

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


def test_same_target_returns_same_lock_instance():
    """同 target → 同一个 Lock 实例(身份不漂)"""
    lk1 = server._get_evolve_lock("user_pulse")
    lk2 = server._get_evolve_lock("user_pulse")
    assert lk1 is lk2, "同 target 必须返同一 Lock 实例,否则并发互斥失效"


def test_different_targets_get_different_locks():
    """不同 target → 不同 Lock(各 target 独立)"""
    lk_u = server._get_evolve_lock("user_pulse")
    lk_p = server._get_evolve_lock("project_pulse")
    lk_a = server._get_evolve_lock("agent_context")
    assert lk_u is not lk_p
    assert lk_p is not lk_a
    assert lk_u is not lk_a


def test_concurrent_acquire_blocks_second():
    """两 thread 抢同一 target 的 lock → 后者真阻塞(用 Event 验证)"""
    target = "user_pulse_test_concurrent"
    lk = server._get_evolve_lock(target)
    holding = threading.Event()
    released = threading.Event()
    second_acquired = threading.Event()

    def holder():
        with lk:
            holding.set()
            released.wait(timeout=2.0)

    def contender():
        holding.wait(timeout=2.0)         # 等 holder 拿到锁
        with server._get_evolve_lock(target):
            second_acquired.set()

    t1 = threading.Thread(target=holder)
    t2 = threading.Thread(target=contender)
    t1.start()
    t2.start()
    # holder 拿到锁后,contender 必须阻塞(不能在 holder release 之前 set)
    assert holding.wait(timeout=2.0), "holder 应能拿到锁"
    # 给 contender 一些时间,如果它能拿到说明锁失效
    second_acquired.wait(timeout=0.3)
    assert not second_acquired.is_set(), \
        "contender 在 holder 仍持锁时不该拿到 — 锁身份漂或互斥失效"
    # 放 holder,contender 应立刻获锁
    released.set()
    assert second_acquired.wait(timeout=2.0), \
        "holder 放锁后 contender 应立刻获锁"
    t1.join(timeout=2.0)
    t2.join(timeout=2.0)


def test_guard_protects_dict_mutation_under_concurrent_first_access():
    """N 个 thread 同时第一次访问某 target → 只创建一个 Lock(_EVOLVE_LOCKS_GUARD 守字典)"""
    target = "stress_target_" + str(id(test_guard_protects_dict_mutation_under_concurrent_first_access))
    # 提前清掉(防上次测试污染)
    with server._EVOLVE_LOCKS_GUARD:
        server._EVOLVE_LOCKS.pop(target, None)

    seen = []
    barrier = threading.Barrier(8)

    def grab():
        barrier.wait()
        seen.append(server._get_evolve_lock(target))

    threads = [threading.Thread(target=grab) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2.0)

    assert len(seen) == 8
    first = seen[0]
    for lk in seen[1:]:
        assert lk is first, "并发首访下,_EVOLVE_LOCKS_GUARD 必须保证只造一个 Lock"
