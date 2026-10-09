from sentinel.config import get_profile_config, reset_profile_config_cache
from sentinel.graph import extraction


def test_graph_extraction_defaults_are_domain_agnostic() -> None:
    """默认图谱抽取配置应保持行业中立，不得预置金融行业特定术语。

    背景：项目曾从金融专用配置重构为通用配置（见 feat/profile-config-generic）。
    行业特定的实体/关系/指令应通过 profile 定制，而非硬编码进默认值。
    本测试守护该重构不被回退。
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

        graph_extraction_prompt = (
            get_profile_config().prompts.pipeline.graph_extraction.body
        )
        combined_text = "\n".join(
            [
                graph_extraction_prompt,
                *extraction.ENTITY_TYPES,
                *extraction.EDGE_TYPES,
            ]
        )
        # 金融行业特定术语不得出现在默认配置中（应通过 profile 定制）。
        finance_specific_terms = [
            "Customer",
            "Account",
            "Merchant",
            "TransfersFunds",
            "银行",
            "反洗钱",
            "涉诈",
            "虚拟币",
        ]
        for term in finance_specific_terms:
            assert term not in combined_text, (
                f"默认配置不应包含金融特定术语 '{term}'；行业术语应通过 profile 配置"
            )
    finally:
        reset_profile_config_cache()
