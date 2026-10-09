Evaluate the event using the configured risk dimensions.

Base the first assessment on the current event, available related context, and external evidence when provided. Score each dimension consistently, explain the main drivers, and separate confirmed facts from uncertain signals. Recommend practical next actions for monitoring, verification, communication, or response.

Configured risk dimensions: {risk_dimensions}
Analyze the related event context separately from the current event. If context is irrelevant or empty, explain that in history_context_analysis.score_reason and keep dimension scores aligned with the configured risk dimensions only.

Event type: {event_type}
Event summary: {event_summary}
Key entities: {key_entities}
Event time: {event_time}
Source: {source}
Related event context: {related_events}
{output_schema}
