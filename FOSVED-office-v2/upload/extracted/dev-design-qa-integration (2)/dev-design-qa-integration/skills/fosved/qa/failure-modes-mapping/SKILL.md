---
name: failure-modes-mapping
description: Systematically enumerating how a system can fail before writing tests. The paranoid discipline — for every component, ask "what can go wrong here?". Failure modes drive what to test. Without this mapping, tests cover what the developer imagined, missing what they didn't.
---

# Failure Modes Mapping — Enumerate How Things Break

A developer tests what they imagined. An attacker, a weird user, a network glitch, a race condition — they exploit what the developer DIDN'T imagine. Failure modes mapping closes that gap: systematically enumerate failure modes before testing, so tests cover reality not imagination.

## Prerequisites

- System or component to analyze
- `test-strategy-design` understood (this feeds strategy)
- Paranoid mindset engaged

## Core principle

> The bug that hits production is the failure mode you didn't think of. The discipline: don't rely on imagination. Systematically walk failure categories for every component. The map of failure modes IS the map of what to test.

## The failure mode categories

For every component, walk these categories:

### 1. Input failures

- **Empty input** — empty string, empty array, empty object
- **Null/undefined** — missing values where value expected
- **Wrong type** — string where number expected
- **Boundary values** — 0, -1, MAX_INT, MAX_INT+1, empty, one item, max items
- **Malformed** — invalid JSON, broken encoding, truncated data
- **Extreme size** — 10MB string, million-item array
- **Special characters** — Unicode, emoji, RTL text, SQL chars, HTML chars, null bytes
- **Injection attempts** — SQL injection, XSS payload, command injection, prompt injection

### 2. State failures

- **Uninitialized state** — used before setup
- **Stale state** — data changed elsewhere, local copy outdated
- **Concurrent modification** — two operations modifying same data
- **Invalid state transitions** — order goes from "shipped" back to "pending"
- **Partial state** — operation half-completed then interrupted
- **State after error** — is system in clean state after a failure?

### 3. Dependency failures

- **Service down** — database unreachable, API returns 503
- **Service slow** — timeout, latency spike
- **Service wrong** — API returns malformed response, unexpected schema
- **Service rate-limits** — 429 responses
- **Partial failure** — service works for some calls, fails others
- **Dependency version change** — library update changes behavior

### 4. Resource failures

- **Out of memory** — large data exhausts heap
- **Out of disk** — writes fail
- **Connection pool exhausted** — too many concurrent DB connections
- **File descriptor limit** — too many open files
- **CPU saturation** — operation too slow under load

### 5. Concurrency failures

- **Race condition** — outcome depends on timing
- **Deadlock** — two operations waiting on each other
- **Lost update** — two writes, one overwrites the other
- **Dirty read** — reading data mid-modification
- **Order dependence** — works if A before B, fails if B before A

### 6. Network failures

- **Connection drops** — mid-request network loss
- **Timeout** — request takes too long
- **Partial response** — connection drops after partial data
- **DNS failure** — can't resolve hostname
- **Slow network** — works on fast wifi, fails on 3G

### 7. Time failures

- **Timezone issues** — UTC vs local confusion
- **DST transitions** — clock jumps
- **Clock skew** — server clocks disagree
- **Expiry edge cases** — token expires mid-request
- **Date boundaries** — month end, year end, leap year
- **Far future/past dates** — year 2000, year 2038, year 9999

### 8. Permission/auth failures

- **No auth** — request without credentials
- **Wrong auth** — valid credentials, wrong user
- **Expired auth** — token expired
- **Privilege escalation** — user accessing another's data
- **Auth during operation** — session expires mid-task

### 9. AI-specific failures (for LLM systems)

- **Hallucination** — model invents facts
- **Prompt injection** — user input manipulates system prompt
- **Refusal** — model refuses valid request
- **Format violation** — model breaks expected output structure
- **Context overflow** — input exceeds context window
- **Cost explosion** — runaway token usage
- **Latency spike** — model slow under load
- **Provider outage** — LLM API down
- **Output drift** — same prompt, different output (non-determinism)
- **Bias** — model produces biased outputs

### 10. User behavior failures

- **Misuse** — using feature in unintended way
- **Impatience** — clicking twice, navigating away mid-operation
- **Back button** — browser back during multi-step flow
- **Multiple tabs** — same user, two sessions
- **Stale page** — user on old version of page after deploy
- **Copy-paste errors** — extra whitespace, wrong field

## The mapping process

For each component:

1. **Identify the component** — function, module, endpoint, screen, flow
2. **Walk all 10 categories** — for each, ask "does this apply? how would it fail?"
3. **Record applicable failure modes** — specific to this component
4. **Rate each:** likelihood (rare/possible/likely) × impact (minor/moderate/severe/catastrophic)
5. **Prioritize** — high likelihood × high impact first
6. **Decide handling** — test it / handle in code / accept risk / mitigate

Output: failure mode table per component.

## Failure mode table example

For "user login endpoint":

| Failure mode | Category | Likelihood | Impact | Handling |
|--------------|----------|-----------|--------|----------|
| Empty email/password | Input | Likely | Minor | Validate, return 400. Test. |
| SQL injection in email | Input | Possible | Catastrophic | Parameterized queries. Test. |
| Wrong password | Input | Likely | Minor | Return 401, no info leak. Test. |
| User doesn't exist | State | Likely | Minor | Return 401 (not 404 — don't leak existence). Test. |
| DB unreachable | Dependency | Rare | Severe | Return 503, retry logic. Test. |
| Brute force attempt | User behavior | Possible | Severe | Rate limiting. Test. |
| Timing attack on password check | Security | Rare | Moderate | Constant-time comparison. Test. |
| Session token collision | State | Very rare | Severe | Cryptographic randomness. Code review. |
| Concurrent login same user | Concurrency | Possible | Minor | Allow, or handle. Decide. Test if handled. |
| Expired token used | Time | Likely | Minor | Reject, clear instruction. Test. |

Now tests have a clear target list. Coverage is intentional, not imagined.

## FMEA-lite (Failure Mode and Effects Analysis)

For critical systems, formal-ish FMEA:

**Risk Priority Number (RPN)** = Severity × Occurrence × Detection

- Severity: how bad if it happens (1-10)
- Occurrence: how likely (1-10)
- Detection: how hard to catch before production (1-10, higher = harder to catch)

High RPN → priority for testing + mitigation.

Don't over-formalize for small projects. The category walk is the core value.

## Failure modes for AI offices specifically

AI offices (like Fosved-bot) have unique failure surface:

**Routing failures:**
- Request routed to wrong specialist
- Request routed to no specialist (falls through)
- Ambiguous request, routing flaps

**LLM failures:**
- Specialist's LLM call fails — does whole request fail?
- LLM returns malformed structured output — parser breaks?
- LLM hallucinated — wrong info delivered confidently

**Multi-agent failures:**
- One specialist fails — does orchestrator handle gracefully?
- Specialists give conflicting results — resolution works?
- Parallel specialist calls — one slow, blocks all?

**Archive failures:**
- DB write fails after expensive LLM call — work lost?
- Archive publication fails — does main flow continue?

**Cost failures:**
- Runaway loop calling LLM repeatedly
- Expensive model used for trivial task

Map these for every AI office project.

## From failure modes to tests

Each high-priority failure mode → explicit test:

```typescript
describe('login endpoint failure modes', () => {
  test('rejects empty email', async () => {
    const res = await login({ email: '', password: 'x' });
    expect(res.status).toBe(400);
  });

  test('resists SQL injection in email', async () => {
    const res = await login({ 
      email: "' OR '1'='1", 
      password: 'x' 
    });
    expect(res.status).toBe(401);  // not 200, not 500
    // and verify no DB corruption
  });

  test('returns 401 for nonexistent user (no existence leak)', async () => {
    const res = await login({ email: 'ghost@nowhere.com', password: 'x' });
    expect(res.status).toBe(401);
    expect(res.body.error).not.toContain('not found');  // don't leak
  });

  test('handles DB unavailable gracefully', async () => {
    mockDbDown();
    const res = await login({ email: 'real@user.com', password: 'correct' });
    expect(res.status).toBe(503);
  });

  // ... one test per high-priority failure mode
});
```

## Coverage check

After tests written, cross-reference against failure mode table:
- Every high-priority failure mode → has test? ✓
- Medium priority → has test or documented acceptance
- Low priority → noted, maybe deferred

Gaps are explicit decisions, not oversights.

## Anti-patterns

- **Imagination-based testing.** Test only what developer thought of. Misses the rest.
- **Happy-path only.** Tests verify success, never failure. Production breaks on first real failure.
- **Skipping categories.** "Concurrency doesn't apply here" — without checking. Often it does.
- **No prioritization.** Treating all failure modes equally. Test trivial, miss catastrophic.
- **Mapping without testing.** Beautiful failure mode doc, no tests written from it.
- **One-time mapping.** System evolves, failure modes change. Re-map on significant changes.
- **Ignoring AI failure modes.** Testing LLM system like deterministic code. Misses hallucination, injection, drift.
- **Severity blindness.** Treating "typo in label" same as "data corruption". Calibrate.

## Integration

- Feeds `test-strategy-design` — failure modes determine what to test
- `unit-testing-craft` / `integration-testing-patterns` implement the tests
- `security-testing-protocol` deep-dives the security failure modes
- `ai-evals-framework` covers AI-specific failure modes
- `defect-discipline` — when a real defect found, was its failure mode in the map? If not, why?
- `chaos-engineering` actively triggers failure modes in production-like environment
