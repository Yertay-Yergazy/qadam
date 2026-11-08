"""Prompts and output schemas of the LLM drafter, one prompt set per language.

Small models follow the language of the prompt and its example much more than an instruction like "answer in the
meeting's language": with a Russian prompt Qwen3-1.7B translated English task titles into Russian. So the prompt
language follows the fragment. Kazakh is written in Cyrillic and goes with the Russian set (titles stay Kazakh).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_TITLE, MAX_CRITERION, MAX_CRITERIA, MAX_TASKS_PER_WINDOW = 120, 200, 5, 4


@dataclass(frozen=True)
class Prompts:
    extract_system: str
    extract_example: tuple[str, dict]
    refine_system: str
    refine_example: tuple[str, dict]
    participants: str  # "Участники: {names}\n\n"
    fragment: str  # "Фрагмент:\n{text}"

    def extract_user(self, people: list[str] | tuple[str, ...], numbered_text: str) -> str:
        return self.participants.format(names=", ".join(people)) + self.fragment.format(text=numbered_text)

    def refine_user(self, text: str) -> str:
        return self.fragment.format(text=text)


# ---------------------------------------------------------------- Russian (and Kazakh)
_RULES_RU = """Правила:
- Задача — действие, о котором договорились. Идеи без решения («когда-нибудь», «подумаем», «потом решим»), вопросы и рассуждения — не задачи.
- title: коротко, 3–8 слов, на языке встречи, без имён и сроков.
- acceptance_criteria: только критерии готовности, которые прозвучали в тексте. Если их нет — пустой список. Не придумывай."""

RU = Prompts(
    extract_system=f"""Ты выписываешь задачи из расшифровки рабочей встречи. Текст распознан автоматически и может содержать ошибки.
Строки фрагмента пронумерованы; «Имя:» в начале строки — это кто говорит, а не исполнитель.
{_RULES_RU}
- line: номер строки, где прозвучала сама задача.
- assignee: имя исполнителя ровно как в списке участников, только если сказано, что эту задачу делает он. Иначе null.
- due: срок этой задачи словами из текста («пятница», «завтра»), только если его назвали. Иначе null.
- Если задач нет, верни пустой список tasks.""",
    extract_example=(
        "Участники: Марат, Дана\n\nФрагмент:\n1. Марат: Надо переписать форму оплаты.\n2. Марат: Пусть Дана возьмёт, до среды.\n"
        "3. Дана: Готово, когда оплата проходит с телефона.\n4. Дана: И ещё нужно обновить логотип.",
        {
            "tasks": [
                {
                    "line": 1,
                    "title": "Переписать форму оплаты",
                    "acceptance_criteria": ["Оплата проходит с телефона"],
                    "assignee": "Дана",
                    "due": "до среды",
                },
                {"line": 4, "title": "Обновить логотип", "acceptance_criteria": [], "assignee": None, "due": None},
            ]
        },
    ),
    refine_system=f"""Тебе дают фрагмент рабочей встречи, в котором правила нашли возможную задачу.
Реши, договорились ли о ней на самом деле (is_task), и сформулируй её.
{_RULES_RU}""",
    refine_example=(
        "Фрагмент:\nНу надо бы когда-нибудь глянуть логи, но это не срочно, потом решим.",
        {"is_task": False, "title": "Посмотреть логи", "acceptance_criteria": []},
    ),
    participants="Участники: {names}\n\n",
    fragment="Фрагмент:\n{text}",
)

# ---------------------------------------------------------------- English
_RULES_EN = """Rules:
- A task is an action the team agreed on. Ideas without a decision ("someday", "maybe", "let's think about it"), questions and status updates are not tasks.
- title: short, 3–8 words, in English, without names or deadlines.
- acceptance_criteria: only definition-of-done criteria that were actually said. If none, an empty list. Do not invent."""

EN = Prompts(
    extract_system=f"""You list the tasks from a transcript of a work meeting. The text comes from speech recognition and may contain errors.
The fragment's lines are numbered; "Name:" at the start of a line is who speaks, not who does the task.
{_RULES_EN}
- line: the number of the line where the task itself was stated.
- assignee: the owner's name exactly as in the participant list, only if it was said that they do this task. Otherwise null.
- due: this task's deadline in the words of the text ("friday", "tomorrow"), only if one was said. Otherwise null.
- If there are no tasks, return an empty tasks list.""",
    extract_example=(
        "Participants: Mark, Dana\n\nFragment:\n1. Mark: We need to rewrite the payment form.\n2. Mark: Dana will take it, by Wednesday.\n"
        "3. Dana: Done when payment works on a phone.\n4. Dana: We also need to update the logo.",
        {
            "tasks": [
                {
                    "line": 1,
                    "title": "Rewrite the payment form",
                    "acceptance_criteria": ["Payment works on a phone"],
                    "assignee": "Dana",
                    "due": "by Wednesday",
                },
                {"line": 4, "title": "Update the logo", "acceptance_criteria": [], "assignee": None, "due": None},
            ]
        },
    ),
    refine_system=f"""You get a fragment of a work meeting where rules found a possible task.
Decide whether the team really agreed on it (is_task) and phrase it.
{_RULES_EN}""",
    refine_example=(
        "Fragment:\nWe should maybe look at the logs someday, not urgent, let's decide later.",
        {"is_task": False, "title": "Look at the logs", "acceptance_criteria": []},
    ),
    participants="Participants: {names}\n\n",
    fragment="Fragment:\n{text}",
)


def prompts_for(text: str) -> Prompts:
    """English prompts when the fragment is mostly Latin script, Russian ones otherwise (Russian, Kazakh)."""
    latin = len(re.findall(r"[a-zA-Z]", text))
    cyrillic = len(re.findall(r"[а-яёА-ЯЁәғқңөұүһіӘҒҚҢӨҰҮҺІ]", text))
    return EN if latin > cyrillic else RU


# ---------------------------------------------------------------- output schemas (grammar-constrained decoding)
_TITLE = {"type": "string", "maxLength": MAX_TITLE}
_CRITERIA = {"type": "array", "items": {"type": "string", "maxLength": MAX_CRITERION}, "maxItems": MAX_CRITERIA}
_NULLABLE = {"anyOf": [{"type": "string", "maxLength": 60}, {"type": "null"}]}

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "maxItems": MAX_TASKS_PER_WINDOW,
            "items": {
                "type": "object",
                "properties": {
                    "line": {"type": "integer", "minimum": 1},
                    "title": _TITLE,
                    "acceptance_criteria": _CRITERIA,
                    "assignee": _NULLABLE,
                    "due": _NULLABLE,
                },
                "required": ["line", "title", "acceptance_criteria", "assignee", "due"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["tasks"],
    "additionalProperties": False,
}

REFINE_SCHEMA = {
    "type": "object",
    "properties": {"is_task": {"type": "boolean"}, "title": _TITLE, "acceptance_criteria": _CRITERIA},
    "required": ["is_task", "title", "acceptance_criteria"],
    "additionalProperties": False,
}
