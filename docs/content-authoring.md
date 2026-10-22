# Content authoring guide

SkillForge's curriculum is curated, versioned YAML in `apps/catalog/content/`.
`python manage.py seed_catalog` loads every `*.yaml` file in that folder. It is
idempotent: unchanged content is left alone, changed challenge/path content
creates a **new version** (old versions stay, so historical attempts remain
readable exactly as the learner saw them), and entries removed from YAML are
deactivated rather than deleted.

Validate while authoring (no database needed):

```bash
python -m apps.catalog.content_loader          # schema, references, cycles
python -m apps.catalog.verify_solutions        # runs reference solutions vs tests (trusted content only)
```

## File layout

Each file may contain any of the top-level lists `categories`, `skills`,
`challenges`, `paths`. Slugs are global across all files and must be
lowercase-kebab-case (`py-iterators-generators`).

## Skills

```yaml
skills:
  - slug: py-iterators-generators
    name: Iterators & generators
    category: python              # category slug
    difficulty: 3                 # 1 introductory … 5 expert
    review_interval_days: 2       # first review interval (1–30)
    summary: Produce values lazily with generators and understand the iterator protocol.   # ≤ 240 chars
    description: |
      Markdown. Two or three short paragraphs: what the skill is, why it matters
      in real engineering work, common pitfalls.
    objectives:                   # 3–5 concrete, checkable outcomes
      - Explain the iterator protocol (`__iter__` / `__next__`).
      - Write generator functions and generator expressions.
    prerequisites:
      - py-comprehensions                       # shorthand = required, min_mastery 0.55
      - skill: py-control-flow-functions
        strength: recommended                   # required | recommended
        min_mastery: 0.5
    related: [py-asyncio]
```

## Challenges (common fields)

```yaml
challenges:
  - slug: gen-lazy-evaluation-mcq
    skill: py-iterators-generators           # primary skill (mastery evidence weight 1.0)
    secondary_skills: [py-comprehensions]    # optional (evidence weight 0.4)
    kind: multiple_choice                    # see kinds below
    difficulty: 2                            # 1–5, keep within ±1 of the skill difficulty
    minutes: 3                               # realistic estimate, 1–60
    diagnostic: true                         # the first quick MCQ of each skill
    tags: [interview]                        # optional: interview, scenario
    title: What does a generator expression return?
    objective: Recognise that generator expressions are lazy.   # ≤ 300 chars, starts with a verb
    prompt: |
      Markdown shown to the learner. Code in fenced blocks:

      ```python
      squares = (n * n for n in range(10**9))
      ```
    hints:                                   # 2–3 progressive hints; never give the answer away in hint 1
      - Think about when each value is computed.
      - Parentheses here do not create a tuple.
    explanation: |
      Markdown shown AFTER submission: why the correct answer is correct and the
      key idea to remember.
    solution: |
      Optional markdown with a worked/corrected example (shown after submission
      or when the learner explicitly reveals it).
    content: { ... kind-specific, below ... }
```

### Misconceptions

Wrong options, wrong answers and missed rubric criteria can carry a
misconception. **Reuse the same `code` across challenges of the same skill** when
it is the same misunderstanding — this is how "recurring mistakes" are detected.

```yaml
misconception:
  code: generator-is-list          # slug
  label: Thinks generator expressions build a list eagerly
  category: conceptual             # conceptual | syntax | edge_case | logic | incomplete | misread | security | performance
```

## Kind: `multiple_choice`

```yaml
content:
  multiple: false        # true = "select all that apply" with partial credit
  options:
    - id: a
      text: A generator object that yields values on demand
      correct: true
      feedback: Right — nothing is computed until you iterate.
    - id: b
      text: A tuple containing a billion squares
      feedback: Parentheses around a comprehension make a generator expression, not a tuple.
      misconception: {code: generator-is-list, label: Thinks generator expressions build a collection eagerly, category: conceptual}
```

Every option needs `feedback`. Single-answer questions need exactly one correct
option. Write plausible distractors that reflect real misconceptions.

## Kind: `short_answer`

```yaml
content:
  placeholder: e.g. O(n)
  ignore_spaces: true            # optional: remove all whitespace before comparing
  accepted: ["O(n)", "linear", "linear time"]
  patterns: ["o\\(\\s*n\\s*\\)"]   # optional, case-insensitive full-match regexes
  partial:                         # optional partially-correct answers
    - answers: ["O(n log n)"]
      score: 0.4
      feedback: Close, but no sorting is needed here.
  wrong:                           # optional common wrong answers with targeted feedback
    - answers: ["O(n^2)", "O(n2)", "quadratic"]
      feedback: Each element is visited once, so the work grows linearly.
      misconception: {code: nested-loop-assumption, label: Assumes membership checks are linear, category: performance}
```

Answers are normalised (case-folded, trimmed, surrounding quotes/backticks and a
trailing full stop removed, whitespace collapsed). Keep answers short and
unambiguous: a name, a number, a complexity, a keyword, a short expression.

## Kinds: `concept_explanation` and `code_review` (keyword rubric)

The learner writes free text. It is scored deterministically against weighted
criteria; each criterion is met if **any** of its entries matches.

* A plain entry matches case-insensitively where the phrase **starts at a word
  boundary** (prefix match), so `lazi` matches "lazily" and "laziness".
  Hyphens are treated as spaces. Underscores are kept (`select_related`).
* An entry starting with `re:` is a case-insensitive regex.
* Give several synonyms per criterion — learners phrase things differently.
* YAML gotcha: quote words like `"no"`, `"yes"`, `"on"`, `"off"`, `"null"`.

```yaml
content:
  min_words: 25
  max_words: 300
  placeholder: Explain in your own words…
  code: |                     # REQUIRED for code_review: the code being reviewed (optional for concept_explanation)
    def get_orders(request):
        ...
  language: python
  criteria:
    - id: lazy-evaluation
      label: Explains that values are produced lazily, one at a time
      weight: 2
      required: true          # missing a required criterion caps the score below a pass
      any: ["lazi", "on demand", "one at a time", "re:\\bwhen (it is|they are) (requested|needed)"]
      missing_feedback: Explain *when* a generator computes each value.
      misconception: {code: generator-is-list, label: Thinks generators compute everything up front, category: conceptual}
    - id: memory
      label: Mentions the memory benefit
      weight: 1
      any: ["memory", "ram", "doesn't store", "does not store"]
      missing_feedback: What does laziness buy you in terms of memory?
```

Use 3–5 criteria. Code reviews should contain 2–4 real, realistic issues
(security, correctness, performance, maintainability) — one criterion per issue.

## Kind: `debugging`

Learner picks the line containing the defect and explains the fix.

```yaml
content:
  language: python
  code: |
    def average(values):
        total = 0
        for value in values:
            total += value
        return total / len(values) + 1
  bug_lines: [5]             # 1-based line numbers that count as correct
  line_weight: 0.4           # share of the score for the line (rest = explanation rubric)
  min_words: 8
  max_words: 200
  criteria:                  # at least one criterion for the explanation
    - id: off-by-one
      label: Identifies the stray "+ 1"
      weight: 1
      any: ["+ 1", "plus one", "re:\\badd(s|ing)? (one|1)\\b", "extra one"]
      missing_feedback: Look closely at the arithmetic in the return statement.
```

## Kind: `python_code`

Executed only by the sandboxed runner service. Tests are trusted assertion
snippets run in the same namespace after the learner's code.

```yaml
content:
  starter_code: |
    def chunk(items, size):
        """Split items into lists of at most `size` elements."""
        raise NotImplementedError
  reference_solution: |
    def chunk(items, size):
        if size < 1:
            raise ValueError("size must be positive")
        return [items[i:i + size] for i in range(0, len(items), size)]
tests:
  - name: splits evenly
    code: assert chunk([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]
  - name: keeps the remainder
    code: assert chunk([1, 2, 3], 2) == [[1, 2], [3]]
  - name: rejects non-positive sizes
    hidden: true             # hidden tests: name shown, code never shown
    code: |
      try:
          chunk([1], 0)
      except ValueError:
          pass
      else:
          raise AssertionError("expected ValueError")
```

Rules: standard library only, deterministic, no file or network access, no
`print`-based checks, fast (< 1 s). The starter code must fail at least one test.
Include 3–6 tests, at least one visible and at least one hidden edge case.

## Paths

```yaml
paths:
  - slug: python-craftsman
    name: Python Craftsman
    tagline: Write Python that is idiomatic, robust and fast.
    goal_type: python          # python | interviews | django | ai | system_design | communication
    default: true              # the path onboarding assigns for this goal (one per goal)
    premium: false
    icon: file-code-2
    order: 1
    version_notes: Initial curriculum
    description: Markdown.
    milestones:
      - title: Idiomatic foundations
        description: …
        steps:
          - py-data-structures              # target mastery 0.7 by default
          - skill: py-comprehensions
            target: 0.75
```
