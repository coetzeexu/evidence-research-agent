"""Persistent execution budget; no restart can replenish calls or elapsed time."""

import asyncio
import json
import time

from langchain.agents.middleware import AgentMiddleware


class BudgetExceeded(RuntimeError):
    pass


class ExecutionBudget:
    def __init__(self, store, run_id, name="execution-budget", seconds=900, calls=64):
        self.store = store
        self.path = store.run_dir(run_id) / f"{name}.json"
        saved = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.elapsed = saved.get("elapsed_seconds", 0.0)
        self.model_calls = saved.get("model_calls", 0)
        self.seconds, self.calls = seconds, calls
        self.started = None

    def start(self):
        if self.started is None:
            self.started = time.monotonic()
            self.persist()

    @property
    def used(self):
        return self.elapsed + (time.monotonic() - self.started if self.started is not None else 0)

    @property
    def remaining(self):
        return max(0.0, self.seconds - self.used)

    @property
    def can_investigate(self):
        return self.used < min(720, self.seconds) and self.model_calls < self.calls - 18

    def snapshot(self):
        return {
            "elapsed_seconds": round(self.used, 3),
            "model_calls": self.model_calls,
            "max_seconds": self.seconds,
            "max_model_calls": self.calls,
        }

    def persist(self):
        # Reserve one heartbeat so a process crash cannot refund the unflushed interval.
        self.store.save_json(
            self.path,
            {**self.snapshot(), "elapsed_seconds": self.used + (5 if self.started is not None else 0)},
        )

    def stop(self):
        self.elapsed = self.used
        self.started = None
        self.persist()

    async def heartbeat(self):
        while True:
            await asyncio.sleep(5)
            self.persist()

    def charge(self):
        self.start()
        if self.remaining <= 0 or self.model_calls >= self.calls:
            raise BudgetExceeded("研究执行或模型调用预算已用完")
        self.model_calls += 1
        self.persist()


class BudgetMiddleware(AgentMiddleware):
    def __init__(self, budget):
        self.budget = budget

    async def awrap_model_call(self, request, handler):
        self.budget.charge()
        async with asyncio.timeout(max(0.01, self.budget.remaining - 1)):
            return await handler(request)
