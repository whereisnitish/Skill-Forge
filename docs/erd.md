# Entity–relationship diagram

Mermaid source; renders on GitHub and in most Markdown viewers. Audit-only and operational tables
(`ContactMessage`, `TaskFailure`, `WebhookEvent`, `UsageRecord`) are listed at the end.

```mermaid
erDiagram
    User ||--|| Profile : has
    User ||--o| OnboardingState : completes
    User ||--o| Subscription : holds
    User ||--o{ LearningGoal : sets
    User ||--o{ LearningSession : "plans per local day"
    User ||--o{ LearningAttempt : submits
    User ||--o{ SkillMastery : "estimated in"
    User ||--o{ ReviewSchedule : "reviews"
    User ||--o{ LearningEvent : "audit log"
    User ||--o{ Notification : receives
    User ||--o{ MentorRequest : asks
    User ||--o{ UserAchievement : earns

    SkillCategory ||--o{ Skill : groups
    Skill ||--o{ SkillPrerequisite : "requires (skill)"
    Skill ||--o{ SkillPrerequisite : "unlocks (prerequisite)"
    Skill }o--o{ Skill : related
    Skill ||--o{ Challenge : "primary skill"
    Challenge }o--o{ Skill : "secondary skills"
    Challenge ||--o{ ChallengeVersion : "versioned as"
    ChallengeVersion ||--o{ ChallengeTestCase : "tested by"

    LearningPath ||--o{ LearningPathVersion : "versioned as"
    LearningPathVersion ||--o{ PathMilestone : contains
    PathMilestone ||--o{ PathStep : contains
    PathStep }o--|| Skill : targets

    LearningGoal }o--o| LearningPath : follows
    LearningGoal }o--o| LearningPathVersion : "pinned to"
    LearningGoal }o--o{ Skill : "focus skills"
    LearningGoal ||--o{ MilestoneCompletion : records
    MilestoneCompletion }o--|| PathMilestone : of

    LearningSession ||--o{ Recommendation : "one at a time"
    Recommendation }o--|| ChallengeVersion : "recommends"
    LearningAttempt }o--|| ChallengeVersion : "answers (frozen)"
    LearningAttempt }o--o| Recommendation : fulfils
    LearningAttempt ||--o| AttemptEvaluation : "evaluated once"
    LearningAttempt ||--o{ SkillEvidence : "moves mastery"
    LearningAttempt ||--o| ReviewRecord : "schedules"
    SkillEvidence }o--|| Skill : about
    SkillMastery }o--|| Skill : of
    ReviewSchedule }o--|| Skill : of
    ReviewSchedule ||--o{ ReviewRecord : history
    AttemptDraft }o--|| ChallengeVersion : "work in progress"
    MentorRequest }o--o| LearningAttempt : explains

    User {
        bigint id PK
        string email UK "case-insensitive unique"
        string display_name
        datetime email_verified_at
    }
    Profile {
        string timezone
        string experience_level
        int daily_minutes
        json preferred_formats
        string theme
        bool reduce_motion
        bool daily_reminder_enabled
        int reminder_hour
    }
    Skill {
        string slug UK
        int difficulty "1-5"
        json learning_objectives
        int review_interval_days
    }
    SkillPrerequisite {
        string strength "required | recommended"
        float min_mastery
    }
    Challenge {
        string slug UK
        string kind
        int difficulty
        int estimated_minutes
        string review_status "AI content needs approval"
        fk current_version
    }
    ChallengeVersion {
        int number "unique per challenge"
        json content
        json hints
        string evaluation_version
        string content_hash
    }
    LearningGoal {
        string status "active | paused | completed | archived"
        bool is_primary "one per user (partial unique index)"
        date target_date
    }
    Recommendation {
        string reason_code
        string reason_text
        json reason_data "component scores"
        float score
        string strategy_version
        string status
    }
    LearningAttempt {
        json response "immutable"
        int hints_used
        bool solution_revealed
        date local_date "learner timezone"
        string status "queued | evaluated | failed"
    }
    AttemptEvaluation {
        float score "0-1"
        string verdict
        json feedback
        json misconceptions
        string evaluator_version
    }
    SkillMastery {
        float alpha
        float beta
        int evidence_count
        int delayed_successes
        string model_version
    }
    SkillEvidence {
        float mastery_before
        float mastery_after
        float weight "1.0 primary, 0.4 secondary"
    }
    ReviewSchedule {
        float interval_days
        float ease
        datetime due_at
        int lapses
    }
```

**Operational tables**

| Table | Purpose | Key constraint |
|---|---|---|
| `Notification` | In-app notifications and email delivery state | unique `(user, dedupe_key)` |
| `UsageRecord` | Daily quota counters (AI mentor) | unique `(user, feature, period)` |
| `WebhookEvent` | Processed provider events | unique `(provider, event_id)` |
| `TaskFailure` | Background tasks that failed after retries | — |
| `ContactMessage` | Contact-form submissions | — |
| `MentorRequest` | Mentor questions, structured responses, token/latency metadata | — |

**Deletion behaviour.** Deleting a user cascades to all of their learning data. Curriculum rows are protected
(`PROTECT`) while referenced by attempts or goals, so history can always be rendered.
