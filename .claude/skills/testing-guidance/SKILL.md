---
name: testing-guidance
description: Testing standards, anti-patterns, and the testing pyramid for algo-trader. Use when planning or reviewing tests, or when implementing features that need test coverage. Emphasizes unit-first testing, meaningful integration/e2e tests, and never leaving critical paths untested.
---

# Testing Guidance

## The Testing Pyramid

```
        /  E2E  \          Few — critical user flows only
       /----------\
      / Integration \      Some — glue between components
     /----------------\
    /    Unit Tests     \  Many — fast, isolated, exhaustive
   /____________________\
```

- **Unit tests**: The foundation. Test every branch, edge case, and error path in isolation. These are fast, deterministic, and cheap to write. Write many of them.
- **Integration tests**: The glue. Verify that components work together correctly (e.g., OrderManager + BrokerAdapter, strategy + indicators). Do NOT re-test logic already covered by unit tests.
- **E2E tests**: The safety net. Cover critical user flows end-to-end (e.g., signal detection -> order submission -> fill handling -> PnL recording). Do NOT re-test what integration tests already cover.

Each layer should provide **unique value**. If a test at a higher layer is only re-verifying what a lower layer already tests, delete it and push the coverage down.

## Critical Systems MUST Be Tested

In a trading system, untested code paths are not just technical debt — they are financial risk. These areas are non-negotiable:

### Always test exhaustively
- **Fallback/recovery paths** — What happens when the primary approach fails? When retries are exhausted? When the last-resort fallback also fails? These paths run during production incidents — the worst time to discover a bug.
- **Order lifecycle edge cases** — Partial fills, partial cancels, rejected orders, broker timeouts, stale state after crash recovery.
- **Risk management guards** — Position validation, stop-loss placement, daily loss limits, position sizing. Every guard must have a test proving it activates correctly AND a test proving it doesn't false-positive.
- **Error translation** — When broker/API errors are caught and re-raised as domain errors, test that the translation is correct. Incorrect error translation causes callers to take the wrong recovery action.
- **PnL calculations** — Both long and short sides. Both percentage and absolute. Both zero and non-zero denominators. Wrong PnL corrupts performance metrics and risk decisions downstream.
- **State machine transitions** — Every valid transition AND every invalid transition that should be rejected.

### The "production incident" test
Ask: "If this code has a bug, will we discover it during a calm trading day, or during a crisis?" If the answer is "during a crisis," that code needs tests NOW. Crash recovery, fallback paths, and error handlers are the highest-priority test targets because they only execute when things are already going wrong.

## Anti-Patterns

### 1. Testing the happy path only
**Wrong**: Test that an order submits successfully.
**Right**: Also test what happens when submission fails, when the broker returns an unexpected status, when the network times out, and when retries are exhausted.

### 2. Integration tests that duplicate unit tests
**Wrong**: An integration test that verifies the same validation logic already covered by unit tests, just with more setup.
**Right**: Integration tests verify the *wiring* — that component A calls component B correctly, that data flows through the pipeline, that error propagation crosses boundaries correctly.

### 3. Mocking what you own and can test directly
**Wrong**: Mocking your own `RiskManager` when testing `OrderManager`, when you could use the real `RiskManager` with controlled inputs.
**Right**: Mock external boundaries (broker APIs, network calls, clocks). Use real implementations for internal components when feasible. Mocks hide bugs at integration points.

**Rule of thumb**: Mock at the system boundary, not at the class boundary.

### 4. Testing third-party library internals
**Wrong**: Testing that SQLAlchemy correctly commits a transaction, that Pydantic validates a field type, or that `asyncio.Queue` is thread-safe.
**Right**: Test YOUR code that USES these libraries. Trust the library; test your integration with it.

### 5. Asserting implementation details instead of behavior
**Wrong**: Assert that a specific internal method was called with specific args.
**Right**: Assert the observable outcome — the return value, the side effect, the state change. Implementation details change; behavior contracts don't.

### 6. One giant test instead of focused cases
**Wrong**: A single test that sets up a complex scenario and checks 15 things.
**Right**: Many small tests, each with a clear name describing the scenario and expected behavior. When one fails, you know exactly what broke.

### 7. No test for the error path
**Wrong**: Testing that `submit_stop_loss` works when the broker accepts it.
**Right**: Also testing what happens when all 3 retry attempts fail and the market-sell fallback kicks in — AND what happens when the fallback also fails. These are the paths that protect real money.

### 8. Skipping edge cases in financial calculations
**Wrong**: Testing PnL for a simple long trade that profits.
**Right**: Also testing: short trades, zero-quantity guards, zero-cost-basis guards, partial fills, decimal precision, negative prices from bad data.

### 9. Over-mocking to avoid writing fixtures
**Wrong**: Mocking 6 internal classes to avoid setting up realistic test data.
**Right**: Build shared fixtures/factories that create realistic test objects. The upfront cost pays off in more reliable tests that catch real bugs.

### 10. E2E tests for edge cases
**Wrong**: An E2E test that verifies what happens when a broker API returns a 429 rate limit.
**Right**: A unit test for the rate-limit handler, an integration test verifying retry logic with a fake HTTP server. E2E tests are for "does the whole flow work," not for edge cases.

## Test Naming Convention

Use descriptive names that read as specifications:

```python
# Good — describes scenario and expected behavior
def test_submit_stop_loss_returns_market_sell_when_all_retries_exhausted():
def test_validate_position_rejects_negative_quantity():
def test_partial_cancel_exits_remaining_position():

# Bad — vague, says nothing about the scenario
def test_submit_stop_loss():
def test_validate_position():
def test_cancel():
```

## Checklist Before Merging

- [ ] Every new function/method has unit tests covering success AND failure paths
- [ ] Every branch (`if`/`else`/`except`) is exercised by at least one test
- [ ] Fallback and recovery paths have dedicated tests (not just the happy path)
- [ ] Financial calculations tested with edge cases (zero, negative, boundary values)
- [ ] Integration tests verify wiring, not logic already unit-tested
- [ ] No mocks for internal components that could be tested directly
- [ ] No tests for third-party library behavior
- [ ] E2E tests cover critical user flows, not edge cases
- [ ] Test names describe the scenario and expected behavior
