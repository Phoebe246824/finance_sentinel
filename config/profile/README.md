# Runtime profile prompts

`profile.yaml` explicitly declares all 23 prompt paths. The catalog has one
runtime source and does not keep duplicate prompt bodies in pipeline packages
or Dashboard category adapters.

```text
config/profile/
|-- profile.yaml
|-- README.md
`-- prompts/
    |-- pipeline/     # 5 prompts: normalization, classification, graph extraction, two risk stages
    `-- dashboard/    # general + 8 category-specific intent/trend pairs
```

## Ownership and selection

Pipeline and Dashboard stages provide dynamic values. Machine-readable output
schemas and parsing contracts remain in Python and are injected through values
such as `output_schema`; do not copy those contracts into Markdown.

Non-zero-shot Dashboard analysis classifies category and severity, then selects
the matching pair. Unknown or undeclared categories use `general`. A declared
prompt whose file is missing is a Profile load error and does not fall back.

Zero-shot trend generation and graph pre-extraction summarization remain
code-owned. Graph extraction belongs to the catalog but is passed verbatim to
Graphiti without Sentinel interpolation.

## Loading and deployment

`get_profile_config()` lazily loads a typed, immutable catalog from the fixed
`config/profile/` directory and caches it for the process lifetime, like
runtime settings. Restart Sentinel after editing `profile.yaml` or Markdown.

There is no environment variable or Settings override for this directory.
Source and Docker Compose deployments must provide the complete directory;
wheel-only deployment without repository configuration is unsupported.

## Rendering and failures

Use `{variable}` for interpolation and `{{` or `}}` for literal braces. The
loader does not prevalidate placeholders. Ordinary Python formatting failures
become a sanitized `PromptRenderError` when the affected Stage renders the
template and terminate that pipeline run.

The error contains the logical prompt name, source path, and exception type,
but not the original exception message or event values. Process-control
`BaseException` subclasses propagate unchanged. Model, network, and JSON parse
failures retain their existing Stage-specific fallbacks.

Repository contract tests are intentionally stricter than the runtime loader:
every declared file must exist, no Markdown may be orphaned, every template
must use exactly its supported variables, and all category pairs must preserve
stable domain markers and route correctly.

Do not put API keys, passwords, tokens, personal data, or other secrets in
Profile prompts.

## Variables

| Prompt | Variables |
|---|---|
| Pipeline normalization | `raw_content`, `current_datetime`, `output_schema` |
| Pipeline classification | `title`, `raw_content`, `category_options`, `default_event_type`, `summary_instruction`, `output_schema` |
| Pipeline risk (first and second) | `risk_dimensions`, `event_type`, `event_summary`, `key_entities`, `event_time`, `source`, `related_events`, `output_schema` |
| Dashboard intent | `category_name`, `category_confidence`, `event_text` |
| Dashboard trend | `category_name`, `category_confidence`, `severity_name`, `severity_confidence`, `short_term`, `medium_term`, `long_term`, `event_text`, `intent_analysis` |
