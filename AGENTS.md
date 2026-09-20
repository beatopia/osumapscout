# Repository operating guidance

These rules apply to all future Codex work in this repository.

## Scope and workflow

- Implement one ticket only. Complete only the requested ticket and stop.
- Do not implement functionality assigned to future tickets, even when it appears convenient.
- Do not refactor unrelated systems. Report unrelated issues instead of silently fixing them.
- Treat explicit ticket non-goals and allowed-file lists as hard boundaries.
- Introduce infrastructure only when the active ticket explicitly requires it.
- Avoid unnecessary dependencies; add one only when it solves a current, stated need.
- Optimize for developer understanding, clean incremental progress, and explainability rather than implementation speed.

## Implementation quality

- Prefer readable, explicit code over clever abstractions.
- Use Python type hints in Python code.
- Use strict TypeScript when TypeScript exists in the repository.
- Keep route handlers focused on HTTP concerns; do not let them become giant business-logic files.
- When osu! API communication is introduced, isolate it behind a dedicated client or service layer rather than scattering calls through route handlers.
- Explain non-obvious implementation decisions in the completion report or appropriate documentation.
- Run the relevant builds and tests for every implementation ticket and report the actual results.

## Documentation accuracy

Repository documentation must describe reality accurately. Clearly distinguish current implementation from intended or tentative design. Never describe planned functionality as already implemented. Update current-state documentation only to reflect changes the active ticket actually made.
