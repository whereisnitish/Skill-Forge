from __future__ import annotations

from apps.catalog.models import Challenge


def version(slug: str):
    return Challenge.objects.select_related("current_version").get(slug=slug).current_version


def correct_answer(slug: str) -> dict:
    challenge = Challenge.objects.select_related("current_version").get(slug=slug)
    content = challenge.current_version.content
    if challenge.kind == "multiple_choice":
        return {"selected": [o["id"] for o in content["options"] if o.get("correct")]}
    if challenge.kind == "short_answer":
        return {"answer": content["accepted"][0]}
    if challenge.kind == "debugging":
        return {"line": str(content["bug_lines"][0]), "explanation": "The + 1 at the end is wrong; remove it."}
    if challenge.kind == "concept_explanation":
        return {"text": "Generators produce values lazily, one at a time, which saves a lot of memory."}
    raise ValueError(challenge.kind)


def wrong_answer(slug: str) -> dict:
    challenge = Challenge.objects.select_related("current_version").get(slug=slug)
    content = challenge.current_version.content
    if challenge.kind == "multiple_choice":
        return {"selected": [next(o["id"] for o in content["options"] if not o.get("correct"))]}
    if challenge.kind == "short_answer":
        return {"answer": "O(n)"}
    if challenge.kind == "debugging":
        return {"line": "1", "explanation": "Something looks off to me here."}
    return {"text": "I really am not sure about this one at all, sorry about that."}
