# Conventions: <project name>

<!-- Written by the pm agent with the lead, kept in the project at docs/CONVENTIONS.md.
     Every agent reads this instead of rediscovering the codebase. Keep it short and concrete:
     rules a reviewer can answer yes/no to, with one example file (and line range) each. -->

## Stack
<!-- languages, frameworks and versions, package manager, how the repo is laid out -->

## Structure and naming
<!-- where each kind of code lives, file and class naming, layering -->

## Patterns
<!-- error handling, logging, validation, dependency injection, data access, API shapes;
     each with an example: `path/to/file.ts:12-40` -->

## Tests
<!-- where tests live, naming, fixtures/mocks, what a good test looks like (example file) -->

## Commands

Run from the project root. Output is trimmed so it doesn't flood the agents' context.

| Purpose | Command |
|---------|---------|
| Tests for the code you changed | |
| Full test suite (once, before hand-off) | |
| Type-check / compile check (fast, errors only) | |
| Build (only when a criterion needs it) | |
| Lint | |

<!-- Examples to adapt:
  Angular   tests for one area  npx ng test --watch=false --browsers=ChromeHeadless --include='src/app/<area>/**/*.spec.ts' 2>&1 | tail -40
            full suite          npx ng test --watch=false --browsers=ChromeHeadless 2>&1 | tail -40
            type-check          npx tsc --noEmit -p tsconfig.app.json 2>&1 | head -40
            build               npx ng build --progress=false 2>&1 | tail -30
  .NET      one test project    dotnet test tests/<Project> --nologo -v q 2>&1 | tail -40
            compile check       dotnet build --nologo -v q -clp:ErrorsOnly 2>&1 | tail -40
  Python    one test file       pytest -q tests/test_<area>.py 2>&1 | tail -30
            full suite          pytest -q 2>&1 | tail -30 -->

**Never run** (they don't exit, or are too slow or noisy for an agent):
<!-- e.g. ng serve, npm start, ng test without --watch=false, dotnet watch, docker compose up without -d -->
