---
title: "alpaca-py ReplaceOrderRequest qty Expects int, Not float"
category: test-failures
tags: [alpaca-py, mypy, type-checking, decimal-conversion]
module: broker.alpaca.broker
symptom: "mypy error: incompatible type float | None; expected int | None"
root_cause: "ReplaceOrderRequest.qty is int|None, not float|None like price fields"
date_solved: 2026-02-14
---

# alpaca-py ReplaceOrderRequest qty Expects int, Not float

## Error

mypy strict mode reports a type mismatch in `AlpacaBrokerAdapter.replace_order()`:

```
error: Argument "qty" to "ReplaceOrderRequest" has incompatible type "float | None"; expected "int | None"
```

## Failing Code

```python
replace_req = ReplaceOrderRequest(
    qty=float(qty) if qty is not None else None,  # WRONG: produces float | None
    limit_price=float(limit_price) if limit_price is not None else None,
    stop_price=float(stop_price) if stop_price is not None else None,
)
```

## Root Cause

alpaca-py's `ReplaceOrderRequest.qty` field is typed as `int | None`, not `float | None`.
Quantities are always whole shares in Alpaca's API -- fractional shares are not supported
for replace operations. The `limit_price` and `stop_price` fields accept `float | None`,
which is why the pattern works for prices but not for quantity.

Our domain model uses `Decimal` for all quantities and prices. The conversion to Alpaca's
SDK types requires awareness of this mixed typing: `int` for qty, `float` for prices.

## Solution

Use `int(qty)` instead of `float(qty)`:

```python
replace_req = ReplaceOrderRequest(
    qty=int(qty) if qty is not None else None,  # CORRECT: produces int | None
    limit_price=float(limit_price) if limit_price is not None else None,
    stop_price=float(stop_price) if stop_price is not None else None,
)
```

## Related Issue: BarSet Union Type

`StockHistoricalDataClient.get_stock_bars()` returns a union type that includes both
dict-like and non-dict forms. Calling `.get(symbol, [])` on the response requires a
type-ignore comment because mypy cannot narrow the union sufficiently:

```python
alpaca_bars = response.get(symbol, [])  # type: ignore[union-attr]
```

This is a known limitation of alpaca-py's return type annotations. The `type: ignore`
comment is acceptable here because the runtime behavior is correct -- the response object
does support `.get()` in practice.

## Prevention

1. **Always check alpaca-py type stubs** when converting from our `Decimal` domain types.
   Do not assume all numeric fields accept `float`. Alpaca's SDK uses mixed types:
   - `int` for share quantities (`qty`, `filled_qty`)
   - `float` for prices (`limit_price`, `stop_price`, `trail_price`)

2. **Run mypy in strict mode** (`strict = true`) as part of CI. This catches these
   mismatches before they reach runtime.

3. **Wrap Decimal-to-Alpaca conversions** in helper functions that encode the correct
   target type, reducing the chance of applying the wrong conversion across multiple
   call sites.
