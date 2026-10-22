# Curriculum map

The skill graph is defined centrally so prerequisites stay consistent across
content files. `→` lists prerequisites (`(rec)` = recommended, otherwise required).
Difficulty is 1 (introductory) to 5 (expert).

## python.yaml — category `python`

| slug | name | diff | prerequisites | related |
|---|---|---|---|---|
| py-data-structures | Core data structures | 1 | — | algo-hashing |
| py-functions | Functions & arguments | 1 | — | py-closures-scope |
| py-comprehensions | Comprehensions | 2 | py-data-structures | py-iterators-generators |
| py-closures-scope | Scope & closures | 3 | py-functions | py-decorators |
| py-iterators-generators | Iterators & generators | 3 | py-comprehensions, py-functions | py-asyncio |
| py-decorators | Decorators | 3 | py-closures-scope | |
| py-exceptions | Exceptions & error handling | 2 | py-functions | py-context-managers |
| py-context-managers | Context managers | 3 | py-exceptions, py-iterators-generators (rec) | |
| py-oop-dataclasses | Classes, dataclasses & protocols | 2 | py-functions | py-typing |
| py-typing | Type hints | 3 | py-oop-dataclasses | llm-structured-output |
| py-testing-pytest | Testing with pytest | 2 | py-exceptions | |
| py-asyncio | Async programming with asyncio | 4 | py-iterators-generators, py-exceptions | |
| py-performance | Performance & profiling | 4 | py-data-structures, py-iterators-generators | algo-complexity |

## django.yaml — category `django` (+ `backend` skills)

| slug | name | diff | prerequisites | related |
|---|---|---|---|---|
| dj-models-orm | Models & the ORM | 2 | py-oop-dataclasses | sql-joins |
| dj-views-urls | Views, URLs & templates | 2 | py-functions | |
| dj-forms-validation | Forms & validation | 2 | dj-views-urls | |
| dj-query-optimization | ORM query optimisation | 3 | dj-models-orm, sql-joins (rec) | sql-indexes |
| dj-transactions | Transactions & data integrity | 4 | dj-models-orm | background-jobs |
| dj-auth-permissions | Authentication & permissions | 3 | dj-views-urls, dj-models-orm | dj-security |
| dj-migrations | Migrations | 3 | dj-models-orm | |
| dj-security | Django security essentials | 3 | dj-forms-validation, dj-auth-permissions | |

Category `backend` (same file):

| slug | name | diff | prerequisites | related |
|---|---|---|---|---|
| sql-joins | SQL joins & aggregation | 2 | — | dj-models-orm |
| sql-indexes | Indexes & query plans | 3 | sql-joins | dj-query-optimization |
| http-api-design | HTTP & REST API design | 2 | — | |
| caching-strategies | Caching strategies | 3 | http-api-design | sd-rate-limiting |
| background-jobs | Background jobs & idempotency | 4 | py-exceptions, http-api-design (rec) | dj-transactions |

## systems.yaml — categories `system-design` and `communication`

| slug | name | diff | prerequisites | related |
|---|---|---|---|---|
| sd-scalability | Scalability fundamentals | 2 | http-api-design | |
| sd-load-balancing | Load balancing | 3 | sd-scalability | |
| sd-data-partitioning | Replication & partitioning | 4 | sd-scalability, sql-indexes | sd-consistency |
| sd-consistency | Consistency & CAP trade-offs | 4 | sd-data-partitioning | |
| sd-rate-limiting | Rate limiting & backpressure | 3 | sd-scalability, caching-strategies | |
| comm-pr-descriptions | Writing clear PR descriptions | 1 | — | |
| comm-code-review-feedback | Giving code review feedback | 2 | comm-pr-descriptions | |
| comm-explaining-tradeoffs | Explaining technical trade-offs | 2 | — | sd-consistency |
| comm-incident-updates | Incident communication | 3 | comm-explaining-tradeoffs | |

## ai_algorithms.yaml — categories `ai-engineering` and `algorithms`

| slug | name | diff | prerequisites | related |
|---|---|---|---|---|
| llm-fundamentals | LLM fundamentals: tokens & context | 1 | — | |
| llm-prompting | Prompt design | 2 | llm-fundamentals | |
| llm-structured-output | Structured output & validation | 3 | llm-prompting, py-typing (rec) | py-typing |
| llm-rag | Retrieval-augmented generation | 3 | llm-prompting | |
| llm-evaluation | Evaluating LLM systems | 4 | llm-rag, llm-structured-output | |
| llm-tool-use | Tool use & agents | 4 | llm-structured-output | |
| algo-complexity | Big-O complexity | 1 | — | py-performance |
| algo-hashing | Hash maps & sets | 2 | algo-complexity, py-data-structures | |
| algo-two-pointers | Two pointers & sliding window | 3 | algo-complexity | |
| algo-recursion | Recursion | 3 | algo-complexity, py-functions | |
| algo-binary-search | Binary search | 3 | algo-complexity | |
| algo-graphs | Graph traversal (BFS/DFS) | 4 | algo-recursion, algo-hashing | |

Relations are symmetrical; list each relation in one place only.
