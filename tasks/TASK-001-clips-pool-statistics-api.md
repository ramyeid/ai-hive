---
id: TASK-001
title: Clips pool statistics API
project: /Users/ramyeid/AlMentor/workspace/almentor-clips     # set by new_task.py — all work for this task happens in this folder
base: main        # branch to start from and review against
status: done
priority: medium        # low | medium | high | urgent
branch: task/TASK-001-clips-pool-statistics-api
created: 2026-10-19
approved: 2026-10-19    # pm: date the lead explicitly approved the final readback — required for ready-for-dev
---

## Problem / Goal
Admins cannot currently see how full users' clips pools are. Pools are Redis lists that users drain as they watch, and the populator refills them to a target size (100 for active users, 50 for passive users).

Goal: one admin-only endpoint that returns, for **every user who should have a pool** (every row of `UserClipsEngagements`):
- a distribution of how many users currently have each pool size, and
- per user: the current pool size and the size the pool has when full.

Success: an admin calling `GET /Clips/api/clips/users/pool/statistics` gets those numbers for all users in one `200` response, with no pagination.

## User Stories
- As an **admin**, I want to see how many users share each current pool size, so I can tell whether pools are being drained faster than the populator refills them.
- As an **admin**, I want each user's current pool size next to their full pool size, so I can spot users with empty or short pools.

## Acceptance Criteria
Config values used below are the RestApi `appsettings.json` defaults: `ActiveUserClipsPoolSize = 100`, `PassiveUserClipsPoolSize = 50`, `PassiveUserThreshold = 14.00:00:00`. "now" = `IDateTimeProvider.GetUtcNow()`.

**Endpoint & auth**
1. **Given** an admin with a valid unicorn token (in integration tests: `ComputeEncodedToken(UserId1)`, as in `ClipControllerIntegrationTest`), **when** they send `GET /api/clips/users/pool/statistics`, **then** the response is `200` with `Content-Type: application/json` and a body of the shape in AC 6.
2. **Given** a caller whose token is for `MockAuthorizer.UnauthenticatedUser`, **when** they send `GET /api/clips/users/pool/statistics`, **then** the response is `401` with body `Invalid unicorn request` (produced by `[AuthorizationFilter(GroupedRoles.AnyAdmin)]`, as for `GET /api/clips`).

**Which users are included**
3. **Given** `UserClipsEngagements` rows for `userId1`, `userId2`, `userId5`, Redis lists for `userId1`, `userId2`, `userId3`, `userId4`, and `0000-0000-0000-0000`, **when** statistics are requested, **then** `users` contains exactly `userId1`, `userId2`, `userId5`. `userId3`, `userId4` (no engagement row) and `0000-0000-0000-0000` are absent everywhere in the response.
4. **Given** a user with an engagement row whose Redis list is missing or empty, **when** statistics are requested, **then** that user appears with `currentPoolSize: 0` and is counted in the `poolSize: 0` bucket.

**Values**
5. **Given** a user's Redis list has length `N`, **when** statistics are requested, **then** their `currentPoolSize` is `N` (Redis `LLEN`).
6. Response body shape (camelCase, System.Text.Json defaults):
   ```json
   {
     "usersCountPerPoolSize": [ { "poolSize": 10, "usersCount": 2 }, { "poolSize": 0, "usersCount": 1 } ],
     "users": [
       { "userId": "userId1", "currentPoolSize": 10, "fullPoolSize": 100 },
       { "userId": "userId2", "currentPoolSize": 10, "fullPoolSize": 50 },
       { "userId": "userId5", "currentPoolSize": 0, "fullPoolSize": 50 }
     ]
   }
   ```
7. **Given** a user with `LastInteractionDate = now − 1 day`, **then** `fullPoolSize` is `100`.
8. **Given** a user with `LastInteractionDate = now − 30 days`, **then** `fullPoolSize` is `50`.
9. **Given** a user with `LastInteractionDate = null`, **then** `fullPoolSize` is `50`.
10. `fullPoolSize` is computed by the **same** method the populator uses: `IClipsPoolPopulatorService.GetUserClipsPoolSize(...)`, called with the three config values above. The rule's logic is unchanged (passive if `LastInteractionDate` is null or `LastInteractionDate + PassiveUserThreshold < now`, otherwise active), and `ClipsPoolPopulatorService.PopulateUserClipsPool` still produces the same pools as before.

**Grouping & ordering**
11. `usersCountPerPoolSize` has one entry per distinct `currentPoolSize` among the included users. `usersCount` = number of included users with that current size. Sizes no user has are not listed. The list is sorted by `poolSize` **descending**.
12. `users` is sorted by `userId` **ascending** (ordinal string comparison).
13. Sum of all `usersCount` == number of entries in `users` == number of rows in `UserClipsEngagements`.

**Edge case**
14. **Given** `UserClipsEngagements` is empty, **when** statistics are requested, **then** the response is `200` with body `{"usersCountPerPoolSize":[],"users":[]}`.

**Integration test scenario (exact data)**
15. In `ClipsPoolStatisticsControllerIntegrationTest`, using the factory's pre-seeded Redis lists (`userId1`..`userId4` and the unauthorized user, 10 clips each), the test inserts into `ClipsDbContext.UserClipsEngagements`: `userId1` with `LastInteractionDate = DateTime.UtcNow`, `userId2` with `DateTime.UtcNow.AddDays(-30)`, `userId5` with `null`. A `GET` as admin returns exactly the body in AC 6.

## Out of Scope
- Any change to how pools are stored or populated: no new Redis keys, no storing the target size, no change to `ClipsPoolPopulatorService` behaviour (only exposing `GetUserClipsPoolSize` publicly).
- Pagination, filtering or sorting parameters (the endpoint takes no query parameters).
- Statistics on the unauthorized/anonymous pool `0000-0000-0000-0000`.
- Users with a Redis list but no `UserClipsEngagements` row.
- Caching the response, UI/admin page, new config keys, migrations.

## Reference Implementations
| Reference | Why it's similar | Patterns to follow |
|-----------|------------------|----------------|
| `src/presentation/Almentor.Clips.Presentation.RestApi/Controllers/ClipController.cs` | Admin-only GET endpoint | Primary-constructor controller with [Route] + [ApiController], [AuthorizationFilter(GroupedRoles.AnyAdmin)] on the action, XML <summary> doc, one logger.LogInformation per action, return Ok(...), ActionResult<T> return type |
| `src/presentation/Almentor.Clips.Presentation.RestApi/Controllers/UserClipsPoolController.cs` | Same api/clips/users route family and same domain | Route naming, logging message style (backticks around values), thin controller delegating to the service |
| `src/core/Almentor.Clips.Core.Application/IUserClipsPoolService.cs` | Service interface in the same layer | Interface at project root with XML docs per method, Task<T> returns |
| `src/core/Almentor.Clips.Core.Application/Core/UserClipsPoolService.cs` | Service that injects IOptions<ClipsPoolPopulatorConfiguration>, IUserClipsPoolRepository, IClipsPoolPopulatorService | Primary-constructor implementation in Core/, reading config via .Value.<Property>, calling repositories and returning DTOs |
| `src/core/Almentor.Clips.Core.Application/Models/ClipsPoolDto.cs` | DTO with nested records | Positional record with nested records, Equals override using SequenceEqual on lists, GetHashCode override |
| `src/core/Almentor.Clips.Core.Application/DependencyInjection.cs` | Service registration | services.AddScoped<IClipsPoolStatisticsService, ClipsPoolStatisticsService>(); alongside the others |
| `src/infrastructure/Almentor.Clips.Infrastructure.Persistence/Repositories/UserClipsPoolRepository.cs` | Redis access for pools | redisContext.GetDatabase(), db.CreateBatch() + batch.Execute() + await Task.WhenAll(...) (from OverwriteClipsPool), Math.Clamp of long length to int (from GetRandomFromClipsPool) |
| `src/infrastructure/Almentor.Clips.Infrastructure.Persistence/Repositories/UserClipsEngagementRepository.cs` | EF reads of engagements | context.UserClipsEngagements.OrderBy(engagement => engagement.Id)...ToListAsync() |
| `src/core/Almentor.Clips.Core.PoolPopulator/Core/ClipsPoolPopulatorService.cs` | Holds the full-size rule (GetUserClipsPoolSize) | Make the existing private method public and add it to IClipsPoolPopulatorService; keep its XML doc and logic unchanged |
| `tests/Almentor.Clips.Tests.Presentation.RestApi/UserClipsPoolControllerTest.cs` | Controller unit tests | xUnit [Fact], Moq service + Mock<ILogger<T>>, Assert.IsType<OkObjectResult>, Assert.IsAssignableFrom<TDto>, Verify(..., Times.Once), Should... test names |
| `tests/Almentor.Clips.Tests.Core.Application/UserClipsPoolServiceTest.cs` | Service unit tests | Mocked repositories / options, same naming and assertion style |
| `tests/Almentor.Clips.Tests.Infrastructure.Persistence/UserClipsPoolRepositoryTest.cs` | Redis repository unit tests | MockDatabase / MockRedisContext / Mock<IBatch> helpers |
| `tests/Almentor.Clips.Tests.Infrastructure.Persistence/UserClipsEngagementRepositoryTest.cs` | EF repository unit tests | BuildClipsDbContextWithInMemoryDb(Guid.NewGuid().ToString()), static engagement fixtures |
| `tests/Almentor.Clips.Tests.Core.PoolPopulator/ClipsPoolPopulatorServiceTest.cs` | Populator unit tests | Where tests for the now-public GetUserClipsPoolSize go |
| `tests/Almentor.Clips.IntegrationTests/ClipsService/ClipControllerIntegrationTest.cs` | Integration tests of an admin endpoint | IClassFixture<ClipsServiceApplicationFactory<Program>>, _tokenService.Encode / ComputeEncodedToken, BuildRequest(Get, ..., legacyAuthorization, token, Device), 401 + Invalid unicorn request assertion |
| `tests/Almentor.Clips.IntegrationTests/ClipsService/UserClipsPoolControllerIntegrationTest.cs` | Integration test that uses Redis + ClipsDbContext | Resolving ClipsDbContext / repositories from factory.Services, JSON deserialization of the DTO and Assert.Equal on the whole DTO |

## Conventions to Follow
**Files & naming**
- New controller: `src/presentation/Almentor.Clips.Presentation.RestApi/Controllers/ClipsPoolStatisticsController.cs`, class `ClipsPoolStatisticsController(IClipsPoolStatisticsService clipsPoolStatisticsService, ILogger<ClipsPoolStatisticsController> logger) : ControllerBase`, `[Route("api/clips/users/pool/statistics")]`, `[ApiController]`.
- Action: `[HttpGet]` + `[AuthorizationFilter(GroupedRoles.AnyAdmin)]`, `public async Task<ActionResult<ClipsPoolStatisticsDto>> GetClipsPoolStatistics()`, logs exactly `logger.LogInformation("Get clips pool statistics")`, returns `Ok(await clipsPoolStatisticsService.GetClipsPoolStatistics())`. No query parameters, no `IAuthorizer`.
- New interface `src/core/Almentor.Clips.Core.Application/IClipsPoolStatisticsService.cs` with `Task<ClipsPoolStatisticsDto> GetClipsPoolStatistics();` (XML doc).
- New implementation `src/core/Almentor.Clips.Core.Application/Core/ClipsPoolStatisticsService.cs`: `ClipsPoolStatisticsService(IOptions<ClipsPoolPopulatorConfiguration> clipsPoolPopulatorConfiguration, IUserClipsEngagementRepository userClipsEngagementRepository, IUserClipsPoolRepository userClipsPoolRepository, IClipsPoolPopulatorService clipsPoolPopulatorService) : IClipsPoolStatisticsService`. Registered with `AddScoped` in `Core.Application/DependencyInjection.cs`.
- New DTO `src/core/Almentor.Clips.Core.Application/Models/ClipsPoolStatisticsDto.cs`:
  `public record ClipsPoolStatisticsDto(List<ClipsPoolStatisticsDto.UsersCountPerPoolSizeDto> UsersCountPerPoolSize, List<ClipsPoolStatisticsDto.UserClipsPoolSizeDto> Users)` with nested `public record UsersCountPerPoolSizeDto(int PoolSize, int UsersCount);` and `public record UserClipsPoolSizeDto(string UserId, int CurrentPoolSize, int FullPoolSize);`, plus `Equals` (both lists `SequenceEqual`) / `GetHashCode` overrides like `ClipsPoolDto`.
- New repository methods (interface with XML doc + implementation):
  - `IUserClipsEngagementRepository.GetAllUserClipsEngagements()` → `Task<List<UserClipsEngagement>>`, ordered by `Id`.
  - `IUserClipsPoolRepository.GetClipsPoolsSizes(List<string> userIds)` → `Task<Dictionary<string, int>>`. One `CreateBatch()` with one `ListLengthAsync(userId)` per user, `batch.Execute()`, `await Task.WhenAll(...)`. Each length clamped to `int` with `Math.Clamp(..., 0, int.MaxValue)`. A missing key gives `0`. An empty `userIds` returns an empty dictionary.
- `IClipsPoolPopulatorService` gains `int GetUserClipsPoolSize(UserClipsEngagement userClipsEngagement, int activeUserClipsPoolSize, int passiveUserClipsPoolSize, TimeSpan passiveUserThreshold);`. `ClipsPoolPopulatorService`'s existing private method becomes that public implementation, with no logic change, and the populator keeps calling it.

**Layering**
- Controller → `IClipsPoolStatisticsService` → repositories + `IClipsPoolPopulatorService`. No Redis/EF access outside the repositories. The grouping/sorting logic lives in `ClipsPoolStatisticsService`.
- Exactly one call to `GetAllUserClipsEngagements()` and one call to `GetClipsPoolsSizes(...)` per request (no per-user DB or Redis round trips).
- `UserClipsPoolController`, `IUserClipsPoolService` and `UserClipsPoolService` are **not** modified.

**Error handling & logging**
- No try/catch in the new code; unexpected exceptions are left to the existing `ErrorHandlingMiddleware` (`500`).
- Only the single controller log line above; no per-user log lines.

**Style**
- Primary constructors, file-scoped namespaces, `var`, LINQ, `static` usings where the references use them; match the XML doc style of the references.

**Tests** (xUnit + Moq, `Should...` names, in existing test projects)
- `tests/Almentor.Clips.Tests.Presentation.RestApi/ClipsPoolStatisticsControllerTest.cs`: returns `OkObjectResult` with the service's DTO; service called once.
- `tests/Almentor.Clips.Tests.Core.Application/ClipsPoolStatisticsServiceTest.cs`: covers AC 3–5, 7–9, 11–14 with mocked repositories, mocked `IClipsPoolPopulatorService` and options.
- Add to `UserClipsPoolRepositoryTest.cs` (sizes incl. missing key → 0, empty input → empty dictionary) and `UserClipsEngagementRepositoryTest.cs` (all rows returned ordered by `Id`, empty table → empty list).
- Add to `ClipsPoolPopulatorServiceTest.cs`: `GetUserClipsPoolSize` returns active for recent, passive for old, passive for null (AC 7–9); existing populator tests still pass unchanged.
- New `tests/Almentor.Clips.IntegrationTests/ClipsService/ClipsPoolStatisticsControllerIntegrationTest.cs`: AC 2 and AC 15.
- All existing tests must still pass.

No new patterns or dependencies beyond those listed.

## Technical Notes
<!-- pm: constraints, affected areas, links. dev may append. -->
Research findings (pm, 2026-10-19):
- Each user's pool is a Redis list keyed by the bare `userId` (`UserClipsPoolRepository`). The unauthorized user's pool is key `0000-0000-0000-0000`.
- The "full" pool size is **not stored anywhere**. `ClipsPoolPopulatorService.GetUserClipsPoolSize` works it out on every run: `PassiveUserClipsPoolSize` (50) if `UserClipsEngagement.LastInteractionDate` is null or older than `PassiveUserThreshold` (14 days), otherwise `ActiveUserClipsPoolSize` (100). That config is bound in the RestApi `appsettings.json` and injected as `IOptions<ClipsPoolPopulatorConfiguration>` into `UserClipsPoolService`.
- Because `fullPoolSize` is computed at request time, a user who crossed the 14-day threshold since the last populator run shows the size the **next** run will target. This was accepted by the lead (Clarification 5).
- The set of users the populator handles = rows of `UserClipsEngagements` (Postgres/EF). `UserId` has a unique index (migration `20241107111953_AddUniqueIndexOnUserClipsEngagement`), so no duplicates.
- Admin-only endpoints use `[AuthorizationFilter(GroupedRoles.AnyAdmin)]` (`ClipController`). The app has path base `/Clips`; integration tests call the route without it.
- The integration test SQL seed (`clips-schema.sql`) contains no engagement rows; the new integration test inserts its own (AC 15). Each test class gets its own containers via `IClassFixture`.
- In integration tests `MockAlmentorUnicornSsoAuthRepository` gives every user privilege `03`, so a valid token for `UserId1` is an admin.

## Clarifications
<!-- pm: every question asked and the lead's answer, in order. The audit trail of decisions. -->
| # | Question | Lead's answer |
|---|----------|---------------|
| 1 | Which users are counted? | Every user who **should** have a pool, i.e. every row in `UserClipsEngagements`, not only users with a non-empty Redis list. A pool that is consumed/missing counts as current size `0`. (2026-10-19) |
| 2 | Who can call the endpoint? | Admins only. (2026-10-19) |
| 3 | Pagination? | None; one response covers all users. (2026-10-19) |
| 4 | Code style? | Must be very similar to the existing code in this project (same layering and patterns). (2026-10-19) |
| 5 | "Full" pool size isn't stored. Work it out at request time with the populator's rule (100 if `LastInteractionDate` is within 14 days, otherwise 50, from config), shared with the populator rather than duplicated? | Yes. No change to how pools are stored. (2026-10-19) |
| 6 | Route? | `GET /api/clips/users/pool/statistics`. (2026-10-19) |
| 7 | Tests? | Unit tests (controller, service, both repositories) + integration tests (admin happy path with seeded Redis/Postgres, non-admin → `401`). Files: see #15. (2026-10-19) |
| 8 | Anonymous pool `0000-0000-0000-0000`? | Excluded (it has no `UserClipsEngagements` row). (2026-10-19) |
| 9 | Response shape? | `{ "usersCountPerPoolSize": [{ "poolSize", "usersCount" }], "users": [{ "userId", "currentPoolSize", "fullPoolSize" }] }`. Buckets group by **current** size, sorted by `poolSize` descending; only sizes at least one user has, `0` included. `users` sorted by `userId` ascending. (2026-10-19) |
| 10 | No engagement rows? | `200` with both arrays empty. (2026-10-19) |
| 11 | Put it in `UserClipsPoolController` / `IUserClipsPoolService`? | **No.** Create a new controller and a new service whose names contain "Statistics". (2026-10-19) |
| 12 | New files: `ClipsPoolStatisticsController` (class route `api/clips/users/pool/statistics`, `[HttpGet]`, AnyAdmin filter), `IClipsPoolStatisticsService` / `ClipsPoolStatisticsService` (scoped, same injections as `UserClipsPoolService`), `ClipsPoolStatisticsDto` in `Models/`? | Ok. (2026-10-19) |
| 13 | Repository methods on existing repos: `IUserClipsEngagementRepository.GetAllUserClipsEngagements()`, `IUserClipsPoolRepository.GetClipsPoolsSizes(List<string>)` → `Dictionary<string,int>` via one Redis batch of `LLEN`? | Ok. (2026-10-19) |
| 14 | Shared rule: make `GetUserClipsPoolSize(...)` public on `IClipsPoolPopulatorService`, logic unchanged? | Ok. (2026-10-19) |
| 15 | Logging: single `LogInformation("Get clips pool statistics")` in the controller, no per-user logs? | Ok. (2026-10-19) |
| 16 | Test files: new `ClipsPoolStatisticsControllerTest`, `ClipsPoolStatisticsServiceTest`, `ClipsPoolStatisticsControllerIntegrationTest`; new cases in `UserClipsPoolRepositoryTest`, `UserClipsEngagementRepositoryTest`? | Ok. (2026-10-19) |
| 17 | Readback details: DTO nested records `UsersCountPerPoolSizeDto(PoolSize, UsersCount)` / `UserClipsPoolSizeDto(UserId, CurrentPoolSize, FullPoolSize)`; unit tests for now-public `GetUserClipsPoolSize` in `ClipsPoolPopulatorServiceTest`; no latency target (one DB query + one Redis batch per request); no try/catch, existing middleware returns `500`. | Approved with the readback. (2026-10-19) |

## Open Questions
<!-- anyone: unanswered = "- [ ] question"; answered = "- [x] question → answer".
     A task cannot become ready-for-dev while any "- [ ]" remains here. -->

## Definition of Ready
<!-- pm: tick only when actually true. Every box must be [x] before ready-for-dev (checked automatically). -->
- [x] Goal and measurable success confirmed by the lead
- [x] Every user role / actor and their permissions named
- [x] Happy path described step by step
- [x] Edge cases, invalid input and error behaviour specified (exact status codes / messages)
- [x] Data: models, fields, validation, migrations, impact on existing data — covered or confirmed N/A
- [x] Interfaces: API contracts, UI states and copy — covered or confirmed N/A
- [x] Non-functional: performance, security, logging, config/env vars — covered or confirmed N/A
- [x] Out of scope agreed with the lead
- [x] Reference implementations and conventions listed — dev knows which patterns and style to follow
- [x] Every acceptance criterion is verifiable with concrete inputs and expected outputs
- [x] Dev self-audit done: no implementation decision is left to the dev's judgement
- [x] Every assumption confirmed by the lead and logged in Clarifications
- [x] Lead approved the final readback

---

## Dev Log
<!-- dev: dated entries — approach, files changed, how to run, unit tests added -->
### 2026-10-19 — Plan
Branch `task/TASK-001-clips-pool-statistics-api` from `main`.
- `IClipsPoolPopulatorService` / `ClipsPoolPopulatorService`: private `GetUserClipsPoolSize` → public + on the interface, logic/doc unchanged (AC 10).
- `IUserClipsEngagementRepository` / `UserClipsEngagementRepository`: `GetAllUserClipsEngagements()` ordered by `Id` (AC 3, 13).
- `IUserClipsPoolRepository` / `UserClipsPoolRepository`: `GetClipsPoolsSizes(List<string>)`, one batch of `ListLengthAsync`, clamped to int (AC 4, 5).
- `Models/ClipsPoolStatisticsDto.cs` with nested records + `Equals`/`GetHashCode` like `ClipsPoolDto` (AC 6).
- `IClipsPoolStatisticsService` + `Core/ClipsPoolStatisticsService`: users from engagements, current size from Redis sizes, full size via `GetUserClipsPoolSize` with config values; users sorted by userId (ordinal), grouped by current size descending (AC 3–5, 7–14). Registered scoped in `DependencyInjection.cs`.
- `Controllers/ClipsPoolStatisticsController.cs`: `[HttpGet]` + AnyAdmin filter, single log line (AC 1, 2).
- Tests: controller, service, both repositories, populator `GetUserClipsPoolSize`, integration test (AC 2, AC 15).

### 2026-10-19 — Handoff
**Changed** (`git diff --stat main...HEAD`: 17 files, +471 / −2; 4 commits):
- `Core.PoolPopulator/IClipsPoolPopulatorService.cs`: adds `GetUserClipsPoolSize` with the XML doc from the implementation.
- `Core.PoolPopulator/Core/ClipsPoolPopulatorService.cs`: `GetUserClipsPoolSize` changed from `private` to `public`. This is the only change; the logic and doc are untouched.
- `Infrastructure.Persistence/IUserClipsEngagementRepository.cs` + `Repositories/UserClipsEngagementRepository.cs`: `GetAllUserClipsEngagements()`, ordered by `Id`.
- `Infrastructure.Persistence/IUserClipsPoolRepository.cs` + `Repositories/UserClipsPoolRepository.cs`: `GetClipsPoolsSizes(List<string>)`. It sends one batch of `ListLengthAsync`, then `Execute` + `Task.WhenAll`, and clamps each length to `int`.
- `Core.Application/Models/ClipsPoolStatisticsDto.cs`: DTO with nested records, plus `Equals`/`GetHashCode` like `ClipsPoolDto`.
- `Core.Application/IClipsPoolStatisticsService.cs` + `Core/ClipsPoolStatisticsService.cs`: builds the users list and the grouping/sorting.
- `Core.Application/DependencyInjection.cs`: `AddScoped<IClipsPoolStatisticsService, ClipsPoolStatisticsService>()`.
- `RestApi/Controllers/ClipsPoolStatisticsController.cs`: the endpoint.
- Tests: `ClipsPoolStatisticsControllerTest` and `ClipsPoolStatisticsServiceTest` are new. New cases were added to `UserClipsPoolRepositoryTest`, `UserClipsEngagementRepositoryTest` and `ClipsPoolPopulatorServiceTest`. `ClipsPoolStatisticsControllerIntegrationTest` is new.

**Criteria → code:**
- AC 1: `[HttpGet]` + `[AuthorizationFilter(GroupedRoles.AnyAdmin)]` in `ClipsPoolStatisticsController`. Tested in `ClipsPoolStatisticsControllerTest.ShouldReturnOkResponseWithClipsPoolStatistics`. The integration test `ShouldReturnClipsPoolStatisticsOfUsersWithUserClipsEngagement` checks `200` + `application/json`.
- AC 2: same filter. Tested in the integration test `ShouldReturnUnauthorizedIfUserUnauthorizedToAccessGetClipsPoolStatistics` (`401` + `Invalid unicorn request`).
- AC 3, 13: users come only from `GetAllUserClipsEngagements()`, and Redis is queried only for those ids. Tested in `ClipsPoolStatisticsServiceTest.ShouldReturnClipsPoolStatisticsOfAllUsersWithUserClipsEngagement`, which verifies the exact ids sent to `GetClipsPoolsSizes`. The integration test covers it end to end: userId3/4 and `0000-…` are absent.
- AC 4, 5: `GetClipsPoolsSizes` relies on `LLEN`, which returns 0 for a missing key. Tested in `UserClipsPoolRepositoryTest.ShouldReturnClipsPoolSizeOfEachUserInOneBatch` / `ShouldReturnEmptyClipsPoolsSizesIfNoUsers`. In the service test, userId5 has current size 0 and appears in the `0` bucket.
- AC 6: DTO + System.Text.Json defaults. The integration test asserts the exact raw body.
- AC 7–10: the service calls `clipsPoolPopulatorService.GetUserClipsPoolSize(engagement, Active, Passive, Threshold)` from config. `ClipsPoolStatisticsServiceTest.ShouldComputeFullPoolSizeWithClipsPoolPopulatorConfiguration` checks this. The rule itself is tested in `ClipsPoolPopulatorServiceTest.ShouldReturnActiveUserClipsPoolSizeIfUserInteractedWithinThreshold`, `…PassiveUserClipsPoolSizeIfUserInteractedBeforeThreshold` and `…PassiveUserClipsPoolSizeIfUserNeverInteracted`. The existing populator tests pass unchanged.
- AC 11, 12: `GroupBy(CurrentPoolSize)` + `OrderByDescending(PoolSize)`, and `OrderBy(UserId, StringComparer.Ordinal)`. The service test includes `userId10` to prove ordinal ordering (`userId1` < `userId10` < `userId2`) and uses three buckets to prove descending order.
- AC 14: `ClipsPoolStatisticsServiceTest.ShouldReturnEmptyClipsPoolStatisticsIfNoUserClipsEngagements`.
- AC 15: `ClipsPoolStatisticsControllerIntegrationTest.ShouldReturnClipsPoolStatisticsOfUsersWithUserClipsEngagement`, which inserts the exact rows and asserts the exact body.

**Run locally** (in the project folder):
- Unit tests: `dotnet test tests/Almentor.Clips.Tests.Presentation.RestApi`, `…Tests.Core.Application`, `…Tests.Core.PoolPopulator`, `…Tests.Infrastructure.Persistence`, `…Tests.ClipsPopulatorTask`. All pass (28 / 27 / 21 / 49 / 3).
- Integration: `dotnet test tests/Almentor.Clips.IntegrationTests` needs Docker running (Testcontainers). All 38 pass, including the 2 new ones.
- Restore: this machine can't reach the private GitHub feed for `Almentor.Unicorn` (`NU1301`; the `0.*` floating version forces a remote lookup). I restored from the local cache with `dotnet restore Almentor.Clips.sln --source ~/.nuget/packages --source https://api.nuget.org/v3/index.json`, then ran with `--no-restore`. This affected only `obj/`; no tracked files changed.

**Self-review:** done; every changed line maps to an AC or convention. Simplifications:
- The new populator tests use bare mocks except for `IDateTimeProvider`, which is the only dependency the rule reads.
- The service reads sizes with the dictionary indexer and no fallback, because the repository returns an entry for every requested id.

**Notes for the lead:**
- `ClipsPoolStatisticsDto.GetHashCode` uses `HashCode.Combine(UsersCountPerPoolSize, Users)`, because the DTO has two lists. `ClipsPoolDto` returns `Clips.GetHashCode()` for its single list. Both are list-reference hashes, consistent with the existing approach.
- The integration test uses the class-fixture's own containers, so its inserted engagement rows can't leak into other test classes.
- I started Docker Desktop on this machine to run the integration tests; it is still running.

## Review Report
<!-- reviewer: dated entries — verdict, AC-by-AC verification, findings (blocker / should-fix / nit) with evidence -->

### 2026-10-19 — Review round 1
**Verdict:** done
**Commit reviewed:** `b191cb1` (branch `task/TASK-001-clips-pool-statistics-api` vs `main`)
**Diff reviewed:** 17 files, +471 / −2 (4 commits)

**A. Business need**
| AC | Implemented in | Tested by | Result |
|----|----------------|-----------|--------|
| 1 | `ClipsPoolStatisticsController.cs:254-261` (`[HttpGet]`, AnyAdmin filter, `Ok(...)`) | `ClipsPoolStatisticsControllerTest.ShouldReturnOkResponseWithClipsPoolStatistics`; integration `ShouldReturnClipsPoolStatisticsOfUsersWithUserClipsEngagement` (200 + `application/json`) | ✓ |
| 2 | `[AuthorizationFilter(GroupedRoles.AnyAdmin)]` | integration `ShouldReturnUnauthorizedIfUserUnauthorizedToAccessGetClipsPoolStatistics` (401 + `Invalid unicorn request`) | ✓ |
| 3 | `ClipsPoolStatisticsService.cs:25-32`: users built only from `GetAllUserClipsEngagements()`; Redis queried only for those ids | service test verifies the exact ids sent to `GetClipsPoolsSizes`; integration test (userId3/4 and `0000-…` absent) | ✓ |
| 4 | `UserClipsPoolRepository.GetClipsPoolsSizes`: `LLEN` on a missing key gives 0, and every requested id gets an entry | repo test `ShouldReturnClipsPoolSizeOfEachUserInOneBatch` (`invalidUser` → 0); service test (userId5 → 0 bucket); integration test | ✓ |
| 5 | `GetClipsPoolsSizes` (`ListLengthAsync`, `Math.Clamp` to int) | repo test (userId1 → 4); integration test (10) | ✓ |
| 6 | `ClipsPoolStatisticsDto.cs` (nested records, SequenceEqual `Equals`) | integration test asserts the exact raw body | ✓ |
| 7–9 | `ClipsPoolPopulatorService.GetUserClipsPoolSize` (logic unchanged) | `ClipsPoolPopulatorServiceTest.ShouldReturnActive…WithinThreshold` / `…Passive…BeforeThreshold` / `…Passive…NeverInteracted`; integration test (100 / 50 / 50) | ✓ |
| 10 | Service `GetFullClipsPoolSize` calls `IClipsPoolPopulatorService.GetUserClipsPoolSize` with the three config values; the only populator change is `private` → `public`, and the populator still calls it at line 149 | `ShouldComputeFullPoolSizeWithClipsPoolPopulatorConfiguration`; existing populator tests unchanged | ✓ |
| 11 | `GroupBy(CurrentPoolSize)` → `OrderByDescending(PoolSize)` | service test with 3 buckets (345, 10, 0) | ✓ |
| 12 | `OrderBy(UserId, StringComparer.Ordinal)` | service test: `userId1` < `userId10` < `userId2` < `userId5` | ✓ |
| 13 | Exactly one entry per engagement row; buckets are derived from `users` | service test (4 users, counts 1+2+1); integration test | ✓ |
| 14 | Empty engagements → empty ids → empty dictionary → `([], [])` | `ShouldReturnEmptyClipsPoolStatisticsIfNoUserClipsEngagements`; repo `ShouldReturnEmptyClipsPoolsSizesIfNoUsers` | ✓ (the raw JSON for this case comes from the same serializer that AC 6's test covers) |
| 15 | — | `ClipsPoolStatisticsControllerIntegrationTest.ShouldReturnClipsPoolStatisticsOfUsersWithUserClipsEngagement` inserts the exact rows and asserts the exact body. The factory seeds `userId1..4` and `0000-…` with 10 clips each (`ClipsServiceApplicationFactory.cs:239-243`) | ✓ |

Scope: nothing beyond the ACs. No extra endpoints, fields, parameters, config or dependencies. `UserClipsPoolController`, `IUserClipsPoolService` and `UserClipsPoolService` are untouched. There is one DB call and one Redis batch per request.

**B. Consistency:** ✓
- The controller matches `ClipController` (primary constructor, `[Route]` + `[ApiController]`, empty `<summary>` + `<returns>`, single `LogInformation`, `Ok(...)`, `ActionResult<T>`).
- The interface and service match `IUserClipsPoolService` / `UserClipsPoolService` (XML docs, `.Value.<Property>` config reads, `static` using of the DTO).
- The DTO matches `ClipsPoolDto`.
- Repository methods match `OverwriteClipsPool` (batch + `Execute` + `WhenAll`), `GetRandomFromClipsPool` (`Math.Clamp`) and `GetUserClipsEngagements` (`OrderBy(engagement => engagement.Id)`).
- Tests follow their reference files: `Should…` names, `BuildClipsPoolPopulatorConfigurationOptions`, `Mock…` helpers, `MockDatabase` / `MockRedisContext`, `BuildClipsDbContextWithInMemoryDb`, and `ClipControllerIntegrationTest`'s token / `BuildRequest` / 401 pattern.
- The DI registration sits alongside the existing ones. Every rule under Conventions to Follow is met, including names and signatures, no try/catch and no per-user logs.

**C. Simplicity & best practice:** ✓
- The service is one short method plus a private helper.
- There are no new abstractions, no defensive code and no unused code.
- The repository comment explains non-obvious Redis behaviour rather than restating the code.

**Findings**
1. [nit] The new `.cs` files have no UTF-8 BOM, while most existing files have one. Evidence: none; no `.editorconfig`, and 13 tracked files already lack a BOM, so the repo is mixed. Fix (optional): save with a BOM to match the neighbours.
2. [nit] `UserClipsEngagementRepositoryTest.ShouldGetAllUserClipsEngagementsOrderedByIdFromDb` inserts rows in Id order, so it would also pass without `OrderBy`. This is the same approach as the existing pagination tests, so no rule is broken.
