# SOP-DB-021: SQL command not properly ended

> Status: Draft — validate with the responsible DBA/service owner before production use.

- **Trigger / error:** `ORA-00933`
- **Category:** Database operations
- **Environment:** `shared` unless the incident record specifies a validated environment
- **Version/status:** `1.0` / `draft — owner review required`

### 1. Symptoms
The operator, database client, scheduled job, or automation workflow reports: **SQL command not properly ended**.

### 2. Likely cause
SQL syntax or dialect is invalid.

### 3. Initial checks
Capture exact generated SQL and client context.
Record the timestamp with timezone, environment, run/job/correlation ID, exact sanitized error, recent changes, and steps already attempted. Confirm target identity before writes.

### 4. Approved resolution
Correct syntax with code review and test in a safe environment.
Use only approved credentials and change procedures. If the cause is not confirmed or no approved instruction covers the situation, stop and escalate rather than improvising a fix.

### 5. Validation / exit criteria
- Confirm the original error is no longer present using a safe, approved test.
- Validate the business outcome (not just the command/API response); reconcile row counts or output artifacts where relevant.
- Check for side effects, duplicate work, and recurrence.
- Record evidence and obtain owner sign-off where required.

### 6. Escalation
Escalate to the responsible DBA, application/data owner, network/platform team, automation owner, or security team according to the local severity matrix. Include the SOP ID, sanitized evidence, correlation ID, impact, and confirmed-versus-suspected cause. Never include passwords, tokens, private keys, or unnecessary sensitive data.

---
