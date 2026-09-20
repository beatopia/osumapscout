# Manual Verification Guide

## Purpose

Manual verification confirms that a ticket behaves as required in the actual repository. A completion report is evidence to inspect, not a substitute for verification by the developer.

## Principles for implementation tickets

- Run every command specified by the ticket and inspect its real output.
- Exercise the implemented behavior manually rather than relying only on Codex's statement that it works.
- Verify relevant failure, empty, and invalid-input cases as well as the successful path.
- Compare the result directly with the ticket's acceptance criteria and non-goals.
- Review the repository diff and status to confirm unrelated files and functionality were not changed.
- Record unexpected behavior before moving to the next ticket; do not silently treat it as accepted.
- Confirm documentation distinguishes implemented behavior from future plans.

Exact commands and behavioral checks should be added by the ticket that introduces each runnable component.

## T0001 verification

1. Confirm the repository root contains:
   - `README.md`
   - `AGENTS.md`
2. Confirm `docs/` contains:
   - `Full_Design_Document.md`
   - `MVP_Technical_Design.md`
   - `Tickets.md`
   - `Repo_Current_State.md`
   - `Manual_Verification_Guide.md`
3. Run `git status` and inspect the changed paths. There should be only the seven documentation files allowed by T0001.
4. Run `git diff --check` if Git provides it and confirm there are no whitespace errors.
5. Inspect the repository tree and confirm no backend, frontend, database, configuration, dependency, Docker, or CI/CD files were added.
6. Open each README link and confirm its relative path reaches the intended document.
7. Confirm planned functionality is consistently described as planned or tentative, not implemented.
8. Confirm `AGENTS.md` explicitly requires Codex to implement one ticket only.
9. Confirm `Tickets.md` contains T0001 through T0015, marks T0001 as current and complete, and does not add a detailed roadmap beyond T0015.
10. Confirm `Repo_Current_State.md` says application implementation has not started, identifies T0001 as the current completed ticket, and identifies T0002 as the expected next ticket.

Do not begin T0002 as part of this verification.
