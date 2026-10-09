"""
Sentinel 舆情分析系统 — 共享数据模型
=====================================
所有服务共用的 Pydantic 数据模型定义。

设计原则:
  - 模型定义在此文件集中管理
  - 每个模型都包含 trace_id 用于链路追踪
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

# ============================================================
#  枚举类型
# ============================================================


class EventSource(str, Enum):
    """
    事件来源枚举
    """

    NEWS = "news"  # 新闻
    CHAT = "chat"  # 聊天记录
    TRANSACTION = "transaction"  # 交易记录
    BEHAVIOR = "behavior"  # 行为轨迹
    STRING = "string"  # 纯文本线索


class RiskLevel(str, Enum):
    """
    风险等级枚举
    """

    HIGH = "high"  # risk_score >= 0.7
    MEDIUM = "medium"  # risk_score >= 0.4
    LOW = "low"  # risk_score < 0.4


class EventType(str, Enum):
    """
    事件类型枚举（由 TypeClassifier Agent 输出）
    """

    EMERGENCY = "突发事件"  # 突发事故、灾难等
    NEGATIVE = "负面舆情"  # 负面新闻、投诉、丑闻
    POSITIVE = "正面舆情"  # 正面报道、好评
    INFORMATION = "信息传播"  # 信息扩散、热点话题
    BUSINESS = "商业动态"  # 商业活动、市场变化


# ============================================================
#  事件模型
# ============================================================


class KeyEntity(BaseModel):
    """
    关键实体模型
    由 TypeClassifier Agent 提取

    字段:
        name: str   — 实体名称（如 "张三"、"腾讯"）
        type: str   — 实体类型 (PERSON/ORGANIZATION/EVENT/LOCATION/TOPIC/PRODUCT)
    """

    name: str = Field(..., description="实体名称")
    type: str = Field(default="ENTITY", description="实体类型")


class NormalizedEvent(BaseModel):
    """
    标准化事件模型
    由 Ingestion 服务产出，传递给 Classification 服务

    字段:
        event_id: str          — 全局唯一 ID（ULID）
        source: EventSource    — 数据来源
        raw_content: str       — 原始文本内容
        title: str             — 事件标题
        structured_data: dict  — 源特有的结构化字段
        timestamp: datetime    — 事件发生时间
        ingestion_time: datetime — 入库时间
        trace_id: str          — 链路追踪 ID
        content_type: str      — 内容类型 (text/structured/mixed)
        event_type: str        — 事件类型 (突发事件/负面舆情/正面舆情/信息传播/商业动态)
    """

    event_id: str = Field(..., description="全局唯一 ID (ULID)")
    source: EventSource = Field(..., description="数据来源")
    raw_content: str = Field(..., description="原始文本内容")
    title: str = Field(default="", description="事件标题")
    structured_data: dict = Field(
        default_factory=dict, description="源特有的结构化字段"
    )
    timestamp: datetime = Field(
        default_factory=datetime.now, description="事件发生时间"
    )
    ingestion_time: datetime = Field(
        default_factory=datetime.now, description="入库时间"
    )
    trace_id: str = Field(default="", description="链路追踪 ID")
    content_type: str = Field(
        default="text", description="内容类型 (text/structured/mixed)"
    )
    event_type: str = Field(
        default="",
        description="事件类型 (突发事件/负面舆情/正面舆情/信息传播/商业动态)",
    )
    summary: str = Field(default="", description="事件摘要")
    risk_level: RiskLevel = Field(default=RiskLevel.MEDIUM, description="风险等级")
    risk_score: float = Field(
        default=0.5, ge=0.0, le=1.0, description="风险分数 (0.0 ~ 1.0)"
    )
    reasoning: str = Field(default="", description="评级推理过程")
    dimension_scores: dict = Field(
        default_factory=dict,
        description="按当前 profile 配置的风险维度分数",
    )


class ClassifiedEvent(BaseModel):
    """
    分类评级结果模型
    由 Classification 服务产出，传递给 Graph 服务

    字段:
        event_id: str           — 原始事件 ID
        event_type: EventType   — 事件类型
        risk_level: RiskLevel   — 风险等级
        risk_score: float       — 风险分数 (0.0 ~ 1.0)
        key_entities: list      — 关键实体 [{"name": "xxx", "type": "PERSON"}, ...]
        summary: str            — 事件摘要
        reasoning: str          — 评级推理过程
        raw_content: str        — 原始内容（透传，供图谱构图）
        source: EventSource     — 来源（透传）
        title: str              — 标题（透传）
        timestamp: datetime     — 时间（透传）
        trace_id: str           — 链路追踪 ID
        classified_at: datetime — 分类完成时间
    """

    event_id: str = Field(..., description="原始事件 ID")
    event_type: EventType = Field(..., description="事件类型")
    risk_level: RiskLevel = Field(..., description="风险等级")
    risk_score: float = Field(..., ge=0.0, le=1.0, description="风险分数")
    key_entities: list[KeyEntity] = Field(
        default_factory=list, description="关键实体列表"
    )
    summary: str = Field(default="", description="事件摘要")
    reasoning: str = Field(default="", description="评级推理过程")
    raw_content: str = Field(default="", description="原始内容")
    source: EventSource = Field(..., description="来源")
    title: str = Field(default="", description="标题")
    timestamp: datetime = Field(default_factory=datetime.now, description="事件时间")
    trace_id: str = Field(default="", description="链路追踪 ID")
    classified_at: datetime = Field(
        default_factory=datetime.now, description="分类完成时间"
    )
