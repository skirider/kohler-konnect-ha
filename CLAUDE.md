## Workflow Orchestration

### 1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately - don't keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity
- Break every plan into atomic steps - each step should do exactly one thing
- Identify dependencies between steps before starting - never assume order doesn't matter
- If the plan changes mid-execution, rewrite it fully - don't patch it
- Flag ambiguity before starting, not mid-task - ask clarifying questions upfront
- Time-box planning: if a plan takes longer than 10 minutes to write, the problem is not understood well enough

### 2. Subagent Strategy to Keep Main Context Window Clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One task per subagent for focused execution
- Never let the main context window become a dumping ground for exploration noise
- Subagents should return structured summaries, not raw dumps
- If a subagent fails, restart it with a clearer, narrower task - don't retry blindly
- Use subagents for: reading large files, running isolated tests, exploring unfamiliar codebases
- Main agent owns decisions - subagents own information gathering

### 3. Self-Improvement Loop
- After ANY correction from the user: update 'tasks/lessons.md' with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project
- Categorize lessons by type: logic errors, assumption errors, communication errors
- If the same mistake happens twice, escalate the lesson to a hard rule - no exceptions
- Track which lessons are applied per session - lessons not applied are lessons not learned
- Share lessons across similar projects when patterns repeat

### 4. Verification Before Done
- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness
- Verification is not optional - it is the last step of every task
- If no tests exist, write a minimal one before closing the task
- Check edge cases explicitly: empty inputs, nulls, boundary values
- Confirm that your change does not break adjacent behavior
- Get a second opinion from a subagent when confidence is low

### 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes - don't over-engineer
- Challenge your own work before presenting it
- Elegance means: fewer moving parts, clearer intent, easier to delete later
- A solution is not elegant if only you can understand it - clarity is part of elegance
- If two solutions have equal correctness, always pick the simpler one
- Refactor as you go - leave the code cleaner than you found it, but don't go out of scope

### 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests -> then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how
- Reproduce the bug before fixing it - never fix what you haven't seen
- State the root cause before proposing a fix - symptoms and causes are different things
- If a bug has multiple possible causes, rule them out one by one - don't guess
- After fixing: confirm the fix doesn't introduce a regression
- Document what caused the bug in 'tasks/lessons.md' if it was non-obvious

### 7. Communication Protocol
- Always lead with the outcome, then explain the steps - not the other way around
- Use plain language - if a technical term is needed, define it first
- Never make the user ask "what did you just do?" - preempt that question
- Keep updates short during execution, detailed only at completion
- If blocked, say exactly what you need - one specific thing, not a list of options
- Silence is not an option - always confirm when a step is done

### 8. Scope Control
- Do exactly what is asked - nothing more, nothing less
- If you notice a nearby problem, flag it but don't fix it without permission
- Never refactor outside the stated scope, even if the code is messy
- Scope creep is a bug in your behavior - treat it as one
- If the scope is unclear, ask before starting - not halfway through

---

## Security Standards (SaaS & Enterprise Focus)

### 1. Multi-Tenant Isolation & Access Control
- **Prevent IDOR:** Never trust client-provided object IDs without validating tenant ownership and user authorization.
- Always scope database queries and API responses to the current authenticated `tenant_id` or `account_id`.
- Default to "deny" for all permission models; explicitly grant access only where required.

### 2. Zero Secrets in Code
- NEVER hardcode credentials, API keys, access tokens, or cryptographic keys in source code, even for testing.
- Always use environment variables, AWS Secrets Manager, HashiCorp Vault, or the designated secrets provider.
- If you accidentally generate code with a hardcoded secret, immediately self-correct and replace it with an environment variable lookup.

### 3. Safe Logging & Data Privacy
- **No PII/PCI in Logs:** Never log passwords, session tokens, credit card numbers, or Personally Identifiable Information (PII).
- Always use data masking/redaction utilities before logging request payloads or error objects.
- Treat stack traces with caution; ensure they do not leak sensitive environment variables or user data to external monitoring tools.

### 4. Input Trust & Injection Prevention
- Never trust user input. Validate, sanitize, and type-check all incoming data at the boundary.
- Always use parameterized queries or ORMs to prevent SQL/NoSQL Injection. String concatenation in database queries is strictly forbidden.
- Protect against SSRF (Server-Side Request Forgery) by strictly validating and safelisting any URLs provided by users for webhooks or external integrations.
- Always encode output to prevent Cross-Site Scripting (XSS) when rendering data in the UI.

### 5. Principle of Least Privilege
- When defining infrastructure as code (Terraform, IAM roles, DB permissions), assign the absolute minimum permissions necessary. 
- Avoid wildcards (`*`) in IAM policies or database grants.
- Containerized applications should not run as root.

---

## Task Management

1. **Plan First**: Write plan to 'tasks/todo.md' with checkable items
2. **Verify Plan**: Check in before starting implementation
3. **Track Progress**: Mark items complete as you go
4. **Explain Changes**: High-level summary at each step
5. **Document Results**: Add review to 'tasks/todo.md'
6. **Capture Lessons**: Update 'tasks/lessons.md' after corrections
7. **Close the Loop**: Confirm with the user that all acceptance criteria are met before closing

---

## Core Principles

- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **Secure by Default**: Security is not an opt-in feature. If a solution sacrifices security for speed, it is the wrong solution.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact**: Changes should only touch what's necessary. Avoid introducing bugs.
- **Ownership**: You own the outcome, not just the code. If something is broken after your change, it's your responsibility to fix it.
- **No Assumptions**: Never assume a file exists, a service is running, or a variable is set. Verify everything.
- **Reproducibility**: Every action you take should be reproducible by someone else following your steps.
- **Honesty Over Confidence**: If you don't know, say so. A wrong answer delivered confidently does more damage than an honest "I'm not sure."
