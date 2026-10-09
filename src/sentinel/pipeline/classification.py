"""Classification stage helpers."""

from sentinel.config import SentinelSettings, get_profile_config, render_prompt
from sentinel.config.profile import ClassificationProfileConfig, ProfileConfig
from sentinel.models import NormalizedEvent
from sentinel.pipeline.llm_json import generate_pipeline_json
from sentinel.utils.logging import get_logger, print_error, print_info


def event_text(normalized_event: dict | NormalizedEvent) -> tuple[str, str]:
    if isinstance(normalized_event, NormalizedEvent):
        return normalized_event.title, normalized_event.raw_content
    return normalized_event.get("title", ""), normalized_event.get("raw_content", "")


def classification_category_text(
    classification: ClassificationProfileConfig,
) -> str:
    if not classification.categories:
        return "No configured categories."

    lines = []
    for category_id, category in classification.categories.items():
        keyword_text = ", ".join(category.keywords)
        if keyword_text:
            lines.append(
                f"- {category_id}: {category.display_name}; keywords: {keyword_text}"
            )
        else:
            lines.append(f"- {category_id}: {category.display_name}")
    return "\n".join(lines)


def classification_output_schema() -> str:
    return (
        "Return JSON only with these fields: "
        "event_type:str, key_entities:dict, summary:str."
    )


def _render_classification_prompt(
    *,
    profile: ProfileConfig,
    title: str,
    raw_content: str,
) -> str:
    return render_prompt(
        profile.prompts.pipeline.classification,
        category_options=classification_category_text(profile.classification),
        default_event_type=profile.classification.default_event_type,
        summary_instruction=profile.classification.summary_instruction,
        title=title,
        raw_content=raw_content,
        output_schema=classification_output_schema(),
    )


async def classify_event(
    app_settings: SentinelSettings,
    normalized_event: dict | NormalizedEvent,
) -> dict | None:
    logger = get_logger("main.classification")
    title, raw_content = event_text(normalized_event)
    profile = get_profile_config()
    prompt = _render_classification_prompt(
        profile=profile,
        title=title,
        raw_content=raw_content,
    )
    try:
        result_dict = await generate_pipeline_json(
            app_settings,
            prompt=prompt,
            temperature=0.3,
        )
        return {
            "event_type": result_dict.get(
                "event_type",
                profile.classification.default_event_type,
            ),
            "key_entities": result_dict.get("key_entities", {}),
            "summary": result_dict.get("summary", ""),
        }
    except Exception as exc:
        print_error("分类结果解析失败")
        logger.error("parse classification result failed: %s", exc, exc_info=True)
        return None


async def execute_classification(
    app_settings: SentinelSettings,
    normalized_events: NormalizedEvent,
) -> NormalizedEvent:
    logger = get_logger("main.classification")

    classification_result = await classify_event(app_settings, normalized_events)

    if classification_result is None:
        print_error("分类失败，使用默认值")
        return normalized_events

    event_type = classification_result["event_type"]
    key_entities = classification_result["key_entities"]
    summary = classification_result["summary"]

    logger.info(
        "classification result: event_type=%s, entities=%d",
        event_type,
        len(key_entities),
    )

    normalized_events.event_type = event_type
    normalized_events.structured_data = key_entities
    normalized_events.summary = summary

    print_info("分类完成")
    return normalized_events
