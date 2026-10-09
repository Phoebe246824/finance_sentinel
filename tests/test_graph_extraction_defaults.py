from sentinel.config import get_profile_config, reset_profile_config_cache
from sentinel.graph import extraction


def test_graph_extraction_code_defaults_stay_domain_agnostic() -> None:
    """图谱抽取的代码默认值保持行业中立，金融语义由 finance profile 提供。

    背景：项目曾从金融专用配置重构为通用配置，行业语义降级为可替换的
    profile 数据（见 feat/profile-config-generic）。本测试守护该分层：
    代码默认值不得硬编码行业术语；finance 分支的 profile 则应完整
    声明金融图谱 schema 与抽取指令。
    """
    reset_profile_config_cache()
    try:
        assert not hasattr(extraction, "DEFAULT_CUSTOM_INSTRUCTIONS")
        assert set(extraction.ENTITY_TYPES) == {
            "Event",
            "Organization",
            "Person",
            "Location",
            "Topic",
            "Product",
        }
        assert set(extraction.EDGE_TYPES) == {
            "Involves",
            "OccursAt",
            "Affects",
            "Mentions",
            "Causes",
        }

        # finance 分支：金融 schema 与抽取指令应完整声明在 profile 中。
        profile = get_profile_config()
        assert {entity.name for entity in profile.graph.entities} == {
            "Customer",
            "Account",
            "Merchant",
            "Device",
            "RiskSignal",
            "RiskEvent",
        }
        assert {edge.name for edge in profile.graph.edges} == {
            "TransfersFunds",
            "UsesDevice",
            "TriggersSignal",
            "MatchesPattern",
        }
        graph_extraction_prompt = profile.prompts.pipeline.graph_extraction.body
        for finance_marker in (
            "Customer",
            "Account",
            "TransfersFunds",
            "【编号# 名称】",
        ):
            assert finance_marker in graph_extraction_prompt, finance_marker
    finally:
        reset_profile_config_cache()
