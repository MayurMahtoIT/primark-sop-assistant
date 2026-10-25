# SOP-DB-051: View refresh failed due to dependency/link/resource issue

> Status: Draft — validate with the responsible DBA/service owner before production use.

- **Trigger / error:** `Materialized view refresh failed`
- **Category:** Database refresh
- **Environment:** `refresh-target` unless the incident record specifies a validated environment
- **Version/status:** `1.0` / `draft — owner review required`

### 1. Symptoms
The operator, database client, scheduled job, or automation workflow reports: **View refresh failed due to dependency/link/resource issue**.

### 2. Likely cause
Source object or refresh resource unavailable.

### 3. Initial checks
Capture view, method, time, and error stack.
Record the timestamp with timezone, environment, run/job/correlation ID, exact sanitized error, recent changes, and steps already attempted. Confirm target identity before writes.

### 4. Approved resolution
Escalate to DBA/object owner and follow approved refresh plan.
Use only approved credentials and change procedures. If the cause is not confirmed or no approved instruction covers the situation, stop and escalate rather than improvising a fix.

### 5. Validation / exit criteria
- Confirm the original error is no longer present using a safe, approved test.
- Validate the business outcome (not just the command/API response); reconcile row counts or output artifacts where relevant.
- Check for side effects, duplicate work, and recurrence.
- Record evidence and obtain owner sign-off where required.

### 6. Escalation
Escalate to the responsible DBA, application/data owner, network/platform team, automation owner, or security team according to the local severity matrix. Include the SOP ID, sanitized evidence, correlation ID, impact, and confirmed-versus-suspected cause. Never include passwords, tokens, private keys, or unnecessary sensitive data.

---
