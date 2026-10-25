# SOP-DB-096: Batch stopped after some chunks committed

> Status: Draft — validate with the responsible DBA/service owner before production use.

- **Trigger / error:** `Cancellation left partial data`
- **Category:** RPA and batch operations
- **Environment:** `automation-platform` unless the incident record specifies a validated environment
- **Version/status:** `1.0` / `draft — owner review required`

### 1. Symptoms
The operator, database client, scheduled job, or automation workflow reports: **Batch stopped after some chunks committed**.

### 2. Likely cause
Cancellation does not roll back side effects.

### 3. Initial checks
Reconcile run ID/checkpoints with target state and source manifest.
Record the timestamp with timezone, environment, run/job/correlation ID, exact sanitized error, recent changes, and steps already attempted. Confirm target identity before writes.

### 4. Approved resolution
Use approved compensation/reconciliation; don't delete by guesswork.
Use only approved credentials and change procedures. If the cause is not confirmed or no approved instruction covers the situation, stop and escalate rather than improvising a fix.

### 5. Validation / exit criteria
- Confirm the original error is no longer present using a safe, approved test.
- Validate the business outcome (not just the command/API response); reconcile row counts or output artifacts where relevant.
- Check for side effects, duplicate work, and recurrence.
- Record evidence and obtain owner sign-off where required.

### 6. Escalation
Escalate to the responsible DBA, application/data owner, network/platform team, automation owner, or security team according to the local severity matrix. Include the SOP ID, sanitized evidence, correlation ID, impact, and confirmed-versus-suspected cause. Never include passwords, tokens, private keys, or unnecessary sensitive data.

---
