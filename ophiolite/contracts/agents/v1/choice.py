"""ophiolite.agent-choice-rules/1 (E150 s0): the rules of a CHOICE_REQUIRED answer that choice-schema.json cannot state
without new schema keywords. Every reader runs both: the schema for the shape, `choice_problems` for these.

- The choice ids are c1, c2, ... cN in that order (so no two are alike and none is skipped).
- Each fragment's canonical JSON (sorted keys, no spaces, UTF-8) is at most 4096 bytes.

Standard library only (Python 3.10); the Platform tests and the SDK load it from its source text, as they load
folders/v1/folder.py."""
import json

FRAGMENT_BYTES = 4096


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def choice_problems(answer):
    """The problems of `answer` (a choice-required envelope that already passed the schema), each as (path, words); []
    when there are none."""
    problems = []
    choices = answer.get('choices') if isinstance(answer, dict) else None
    if not isinstance(choices, list): return [('$.choices', 'The choices are a list')]
    for index, choice in enumerate(choices):
        path = '$.choices[%d]' % index
        if not isinstance(choice, dict): problems.append((path, 'A choice is an object')); continue
        if choice.get('id') != 'c%d' % (index + 1):
            problems.append((path + '.id', 'Choice %d is named c%d' % (index + 1, index + 1)))
        if len(canonical(choice.get('fragment'))) > FRAGMENT_BYTES:
            problems.append((path + '.fragment', 'A fragment is at most %d bytes of canonical JSON' % FRAGMENT_BYTES))
    return problems
