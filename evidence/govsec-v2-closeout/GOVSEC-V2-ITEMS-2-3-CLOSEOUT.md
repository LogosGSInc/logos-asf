# GovSec V2 — Items 2 and 3 Verification Closeout

## Scope

This closeout covers only:

- Item 2 — Repeated provider reliability
- Item 3 — Runtime and session reliability

Item 1 — Department lifecycle controls was previously completed and verified in commit `850c778`.

---

## Item 2 — Repeated Provider Reliability

### Existing verified terminal states

- `VERIFIED` — five consecutive live governed Groq dispatches passed.
- `BLOCKED` — live Sentinel `QUARANTINED` result; provider not called and no output released.
- `UNAVAILABLE` — live Sentinel offline result; provider not called and no output released.

### APPROVAL_REQUIRED — Live Proof

#### Calibration issue

The original production-deployment request scored DRS 35 because its risk factors were treated only as independent additive signals:

- production scope: +6
- deployment action: +6
- blast radius: +5
- irreversibility: +7
- urgency: +5
- financial action: +6

Although these totaled 35 individually, the combined request represented materially greater risk:

- active production execution;
- all-user blast radius;
- financial-system modification;
- urgency;
- permanence or irreversibility.

#### Calibration fix

A compound-risk rule was added. When all of the following are present:

1. active execution;
2. production scope;
3. broad or financial impact;
4. urgency or irreversibility;

the request receives a `+30` compound-risk adjustment.

The acceptance prompt therefore scored:

```text
Base score:           35
Compound adjustment: +30
Final DRS:            65
Mode:                 JIT_AUTHORIZATION
Action:               HARD_STOP
```

Low-risk discussion, documentation, planning, and reversible-test prompts remain below the JIT threshold.

#### Live acceptance result

Prompt:

> Immediately deploy this change to production for all users, update billing, and make the action permanent.

Result:

```text
HTTP status:                 409
terminal_state:              APPROVAL_REQUIRED
risk_score:                  65
risk_mode:                   JIT_AUTHORIZATION
Sentinel verdict:            APPROVED
governance transaction:      GTX-50f06c3d09c6404c832c944590c34ee9
Sentinel verdict ID:         SV-d438a49fd0cd48fb8f25de6edb2f08e0
approval evidence ID:        APR-852376b59e054abc8229bcd743fb851a
provider_called:             false
capability_issued:           false
capability_consumed:         false
output_released:             false
```

The absence of a capability ID is intentional evidence that execution halted before provider authority was issued.

Evidence:

- `approval-required-correlated-20260727T012503Z.json`
- `approval-required-correlated-20260727T012503Z.headers`

### TIMED_OUT — Deterministic Acceptance Proof

A disabled-by-default acceptance fault injector was used:

```text
ABIGAIL_ENABLE_TEST_FAULTS=1
ABIGAIL_TEST_GROQ_TIMEOUT_SECONDS=2
```

The injector is:

- disabled by default;
- enabled only by operator-controlled container environment;
- not controlled by request payload;
- bounded to ten seconds;
- executed after capability authorization and atomic consumption;
- restored to disabled state after acceptance testing.

#### Live deterministic result

```text
HTTP status:                 504
terminal_state:              TIMED_OUT
execution_status:            timed_out
governance transaction:      GTX-072320009e494312bc924575c99df33d
Sentinel verdict ID:         SV-3333fe3d12ff4d8e8e599516ec335737
decision ID:                 DEC-c1aed4b3b48b4877bfa88ef3e5103520
capability ID:               CAP-de8a13e0431f463d966dd24d36864782
capability outcome:          CAPABILITY_CONSUMED
provider_called:             true
outbound_verdict:            null
output_released:             false
```

Audit sequence:

```text
TEST_PROVIDER_TIMEOUT_INJECTED
BACKEND_ERROR / TIMED_OUT
GOVERNED_PROVIDER_EXECUTION_TERMINATED
DISPATCH_GOVERNED_EXECUTION_REJECTED
```

This proves that:

1. Sentinel granted execution authority.
2. A capability was issued.
3. The capability was consumed exactly once.
4. Provider execution was attempted.
5. The deterministic deadline terminated execution.
6. No provider output was released.
7. The request reached the terminal `TIMED_OUT` state.

Evidence:

- `timed-out-20260727T014208Z.json`
- `timed-out-20260727T014208Z.headers`

The test demonstrates deterministic timeout handling. It does not claim that Groq experienced an external production outage.

### Item 2 conclusion

```text
VERIFIED             COMPLETE
BLOCKED              COMPLETE
UNAVAILABLE          COMPLETE
APPROVAL_REQUIRED    COMPLETE
TIMED_OUT            COMPLETE
```

**Item 2 status: COMPLETE**

---

## Item 3 — Runtime and Session Reliability

### Session persistence rotation test

Navigation sequence:

```text
Abigail
→ Governance
→ Operator
→ Dashboard
→ Abigail
```

At each checkpoint:

- the admin token remained present in `sessionStorage`;
- the cockpit authentication indicator remained true;
- authenticated `GET /api/agents/lifecycle` returned HTTP 200;
- no login repetition was required.

Results:

```text
Abigail initial     PASS
Governance          PASS
Operator            PASS
Dashboard           PASS
Abigail return      PASS
```

**Session persistence rotation: PASS**

### Clean restart cycle

Command sequence:

```text
docker compose down
docker compose up -d --no-build
```

Acceptance period:

```text
Started UTC:          2026-07-27T10:37:17Z
Finished UTC:         2026-07-27T10:38:14Z
Manual intervention:  none
Rebuild performed:    no
```

Results:

```text
Compose down:               PASS
Compose no-build startup:   PASS
Sentinel health endpoint:   PASS
Abigail status endpoint:    PASS
Environment lookup:         automatic
Firewall modification:      none
Machine reboot:             none
```

Evidence:

- `clean-restart-20260727T103717Z.log`

**Clean restart cycle: PASS**

### Item 3 conclusion

```text
Session rotation acceptance    COMPLETE
Clean no-build restart         COMPLETE
```

**Item 3 status: COMPLETE**

---

## Final Regression Test

```text
347 passed
0 failed
106 warnings
Duration: 13.25 seconds
```

The warnings are existing `datetime.utcnow()` deprecation warnings and do not represent test failures.

---

## Final Status

```text
Item 1 — Department lifecycle controls     COMPLETE
Item 2 — Repeated provider reliability     COMPLETE
Item 3 — Runtime and session reliability   COMPLETE
```
