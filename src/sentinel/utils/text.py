"""
Sentinel 工具函数
================
共享的工具函数，避免模块间循环导入。
"""

import json
import re


def extract_subject_id_numbers(text: str) -> list[str]:
    """从事件文本中抽取主体 id_number，例如【P01# 小明】中的 P01。"""
    id_numbers: list[str] = []
    seen: set[str] = set()

    for entity_id in re.findall(r"【\s*([A-Za-z]+\d+)\s*#\s*[^】]+?\s*】", text):
        normalized_id = entity_id.strip().upper()
        if normalized_id and normalized_id not in seen:
            id_numbers.append(normalized_id)
            seen.add(normalized_id)

    for entity_id in re.findall(r"\b([A-Za-z]+\d+)\b", text):
        normalized_id = entity_id.strip().upper()
        if normalized_id and normalized_id not in seen:
            id_numbers.append(normalized_id)
            seen.add(normalized_id)

    return id_numbers


def extract_person_id_numbers(text: str) -> list[str]:
    """只抽取人员 id_number（P 前缀），用于 blacklist/KV 人员路径。"""
    return [
        entity_id
        for entity_id in extract_subject_id_numbers(text)
        if entity_id.startswith("P")
    ]


def sanitize_text_input(text: str) -> str:
    """清洗非法 Unicode、零宽字符和不可见控制字符。"""
    cleaned = text.encode("utf-8", errors="ignore").decode("utf-8")
    zero_width = "\u200b\u200c\u200d\ufeff\u2060"
    for char in zero_width:
        cleaned = cleaned.replace(char, "")
    return "".join(char for char in cleaned if ord(char) >= 32 or char in "\n\r\t")


def parse_llm_json_object(raw_output) -> dict:
    """Parse a JSON object from LLM output, including fenced Markdown JSON."""
    text = str(raw_output).strip()
    if not text:
        raise ValueError("empty LLM output")

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
        raise ValueError(f"expected JSON object, got {type(parsed).__name__}")
    except json.JSONDecodeError:
        pass

    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        fenced_text = "\n".join(lines).strip()
        if fenced_text:
            parsed = json.loads(fenced_text)
            if isinstance(parsed, dict):
                return parsed
            raise ValueError(f"expected JSON object, got {type(parsed).__name__}")

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object found in LLM output")
    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError(f"expected JSON object, got {type(parsed).__name__}")
    return parsed
