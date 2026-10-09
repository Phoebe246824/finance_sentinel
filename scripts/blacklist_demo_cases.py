"""Shared finance-domain blacklist/Milvus demo cases and expected states."""

from __future__ import annotations

from typing import Any

DemoCase = dict[str, Any]

TEST_CASES: list[DemoCase] = [
    {
        "id": "case_01_low_risk_salary_baseline",
        "title": "1. 正常工资入账与日常消费：应写入事件库但不构图",
        "text": "2026年6月10日 09:12，【P101# 客户A】收到【C201# 星河科技有限公司】工资入账 18600 元，随后在【C301# 家乐优超市】刷卡消费 326 元。账户近30天交易频率稳定，登录设备为常用手机，收款方和消费地点均与历史行为一致。",
        "expect": [
            "未命中金融风险关键词",
            "写入 Milvus 事件库",
            "作为后续客户画像和正常行为基线，不进入构图",
        ],
        "expect_state": {
            "milvus": {
                "exists": True,
                "person_ids": ["P101"],
                "is_graph_built": False,
            },
            "neo4j": {"content_count": 0},
        },
    },
    {
        "id": "case_02_structuring_blacklist_recipient_pass",
        "title": "2. 多笔小额转账接近限额且命中收款人黑名单：应进入完整研判",
        "text": "2026年6月12日 21:35，【P102# 客户B】在2小时内向【P203# 收款人甲】、【P204# 收款人乙】、【P205# 收款人丙】分别转账 49000 元、48500 元、49200 元。交易备注均为咨询服务费，收款账户开户时间不足7天。",
        "expect": [
            "P203、P204 命中人员黑名单",
            "即使不直接命中关键词黑名单也应 PASS",
            "保留 P102 与多个新收款方关系",
            "进入分类 / 构图 / 风险评估并作为后续分拆交易上下文",
        ],
        "expect_state": {
            "milvus": {
                "exists": True,
                "person_ids": ["P102", "P203", "P204", "P205"],
                "is_graph_built": True,
            },
            "neo4j": {"content_count": 1},
        },
    },
    {
        "id": "case_03_blacklist_account_pass",
        "title": "3. 黑名单客户异常转账：应 PASS 进入完整研判",
        "text": "2026年6月13日 10:24，【P105# 客户E】尝试向【P305# 涉诈账户】转账 98000 元，交易备注为虚拟币保证金。该收款账户曾被多名客户投诉诱导投资，且交易发起设备为首次登录的新设备，登录城市与客户常驻城市相距较远。",
        "expect": [
            "P105 命中人员黑名单",
            "涉诈、虚拟币、保证金等关键词触发 PASS",
            "进入分类 / 构图 / 风险评估并标记已构图",
        ],
        "expect_state": {
            "milvus": {
                "exists": True,
                "person_ids": ["P105", "P305"],
                "is_graph_built": True,
            },
            "neo4j": {"content_count": 1},
        },
    },
    {
        "id": "case_04_aml_high_risk_recall",
        "title": "4. 洗钱分拆交易：高风险路由与已构图历史不重复补图",
        "text": "2026年6月14日 23:48，【P102# 客户B】再次通过手机银行向4个新开户账户分散转出 196000 元，随后其中两个收款账户在10分钟内继续转入同一虚拟币平台商户。交易行为疑似分拆交易与洗钱资金归集，反洗钱系统要求立即复核并冻结后续出金。",
        "expect": [
            "命中 洗钱 / 分拆交易 / 虚拟币 / 反洗钱 / 冻结 等关键词",
            "图谱检索可复用 case_02 已构图的 P102 历史可疑转账",
            "Milvus 批量回捞只处理未构图候选，已构图历史不应重复补图",
        ],
        "expect_state": {
            "milvus": {
                "exists": True,
                "person_ids": ["P102"],
                "is_graph_built": True,
            },
            "neo4j": {"content_count": 1, "no_duplicate_content": True},
            "after_case": {
                "case_02_structuring_blacklist_recipient_pass": {
                    "milvus": {"is_graph_built": True},
                    "neo4j": {"content_count": 1, "no_duplicate_content": True},
                }
            },
        },
    },
    {
        "id": "case_05_loan_fraud_pass",
        "title": "5. 小微贷款资料疑似造假：触发贷前风控研判",
        "text": "2026年6月15日 15:20，【P106# 个体工商户F】提交经营贷申请 80 万元，系统发现其近7日流水突然放大，多个交易对手与申请人存在同设备登录记录，纳税凭证与银行流水时间不一致，疑似包装流水和贷款欺诈。",
        "expect": [
            "命中 贷款欺诈 / 包装流水 等风险关键词",
            "进入贷前风控智能体分析",
            "生成需要人工复核的证据点",
        ],
        "expect_state": {
            "milvus": {
                "exists": True,
                "person_ids": ["P106"],
                "is_graph_built": True,
            },
            "neo4j": {"content_count": 1},
        },
    },
    {
        "id": "case_06_low_risk_followup_baseline",
        "title": "6. 同一客户正常复访交易：应作为全量事件库独立基线",
        "text": "2026年6月16日 09:18，【P101# 客户A】收到【C202# 星河科技有限公司】季度绩效奖金 8200 元，随后向本人同名储蓄账户转入 3000 元并支付水电费 468 元。登录设备、收款账户和消费场景均为历史常用组合，近7日交易节奏无异常。",
        "expect": [
            "与 case_01 共享 P101 但原文不同，避免 demo 数据重复",
            "未命中黑名单",
            "当前 Milvus 是全量输入事件库，应写入为新的未构图正常行为基线",
        ],
        "expect_state": {
            "milvus": {
                "exists": True,
                "person_ids": ["P101"],
                "is_graph_built": False,
            },
            "neo4j": {"content_count": 0},
        },
    },
    {
        "id": "case_07_no_person_keyword_pass",
        "title": "7. 无客户编号但命中关键词：仍应进入研判",
        "text": "2026年6月16日 03:20，某批量清算任务发现多个新开户账户在凌晨集中向同一虚拟币平台商户转入资金，交易备注为空，反洗钱监控建议暂停该商户后续入金。",
        "expect": [
            "无 P 前缀客户编号",
            "命中 虚拟币 / 反洗钱 关键词",
            "仍应 PASS 进入后续 pipeline",
        ],
        "expect_state": {
            "milvus": {"exists": True, "person_ids": [], "is_graph_built": True},
            "neo4j": {"content_count": 1},
        },
    },
    {
        "id": "case_08_device_geo_anomaly_pass",
        "title": "8. 异地新设备登录后大额转账：设备地理风险",
        "text": "2026年6月16日 08:45，【P107# 客户G】常驻上海，但账户在境外 IP 和新设备上登录后，5分钟内向【P307# 新收款人】转账 120000 元，短信验证码多次失败后才通过，客服回访电话无人接听。",
        "expect": [
            "命中 新设备 / 境外 IP / 短信验证码 等风险关键词",
            "重点观察 device_geo 与 transaction_behavior 维度",
            "适合作为账户盗用或电诈转账风险样本",
        ],
        "expect_state": {
            "milvus": {
                "exists": True,
                "person_ids": ["P107", "P307"],
                "is_graph_built": True,
            },
            "neo4j": {"content_count": 1},
        },
    },
    {
        "id": "case_09_many_to_one_mule_account_pass",
        "title": "9. 多客户向同一新账户归集：疑似跑分收款账户",
        "text": "2026年6月16日 12:30，【P108# 客户H】、【P109# 客户I】、【P110# 客户J】分别向【P308# 新收款账户】转入 30000 元、28000 元、35000 元，随后【P308# 新收款账户】立即向外部支付通道出金。该账户开户不足24小时。",
        "expect": [
            "命中 支付通道 等风险关键词",
            "覆盖多客户共同收款方关系",
            "适合作为跑分和资金归集风险样本",
        ],
        "expect_state": {
            "milvus": {
                "exists": True,
                "person_ids": ["P108", "P109", "P110", "P308"],
                "is_graph_built": True,
            },
            "neo4j": {"content_count": 1, "no_duplicate_content": True},
        },
    },
    {
        "id": "case_10_chargeback_complaint_similarity_pass",
        "title": "10. 投诉线索与涉诈账户相似：测试事件相似度命中",
        "text": "2026年6月17日 18:05，【P111# 客户K】投诉称其被诱导向投资平台缴纳保证金 66000 元，收款账户承诺高收益返利但拒绝提现，客服话术与此前涉诈账户投诉高度相似。",
        "expect": [
            "命中 保证金 / 涉诈 / 投诉 / 返利 等关键词",
            "也可能命中 E-FIN-FRAUD-001 事件相似度",
            "用于展示命中详情打印",
        ],
        "expect_state": {
            "milvus": {
                "exists": True,
                "person_ids": ["P111"],
                "is_graph_built": True,
            },
            "neo4j": {"content_count_at_most": 1, "no_duplicate_content": True},
        },
    },
    {
        "id": "case_11_sanction_screening_pass",
        "title": "11. 跨境汇款触发制裁筛查：应进入合规研判",
        "text": "2026年6月18日 09:40，【P112# 外贸客户L】向【C401# 境外贸易公司】发起美元跨境汇款 240000 美元，收款方名称与制裁名单中的实体高度相似，付款用途填写为设备预付款，但贸易合同缺少最终受益人说明。",
        "expect": [
            "命中 制裁名单 / 跨境汇款 / 最终受益人 等合规关键词",
            "进入 AML 与制裁筛查研判",
            "生成需要补充 KYC/KYB 材料的检查点",
        ],
        "expect_state": {
            "milvus": {
                "exists": True,
                "person_ids": ["P112"],
                "is_graph_built": True,
            },
            "neo4j": {"content_count": 1},
        },
    },
    {
        "id": "case_12_merchant_cashout_pass",
        "title": "12. 商户交易异常退款：疑似套现或虚假交易",
        "text": "2026年6月18日 14:25，【C402# 星桥数码商户】在30分钟内完成18笔同金额刷卡交易，每笔 9999 元，随后集中向【P113# 商户负责人M】绑定账户发起退款。多名持卡人设备指纹相同，交易地点与商户注册地址不一致，疑似套现和虚假交易。",
        "expect": [
            "命中 套现 / 虚假交易 / 退款 / 设备指纹 等风险关键词",
            "进入商户风控图谱分析",
            "观察商户、负责人、持卡设备之间的关联",
        ],
        "expect_state": {
            "milvus": {
                "exists": True,
                "person_ids": ["P113"],
                "is_graph_built": True,
            },
            "neo4j": {"content_count": 1, "no_duplicate_content": True},
        },
    },
    {
        "id": "case_13_account_takeover_pass",
        "title": "13. 账户资料被连续修改后转账：疑似账户接管",
        "text": "2026年6月19日 01:12，【P114# 客户N】账户先后修改登录密码、绑定手机号和收款白名单，随后向【P314# 新收款人】转账 86000 元。修改操作来自非常用设备，IP 归属地异常，短信验证码出现多次重发记录。",
        "expect": [
            "命中 账户接管 / 白名单 / 非常用设备 / 短信验证码 等关键词",
            "进入账户盗用风险研判",
            "适合作为操作行为链路构图样本",
        ],
        "expect_state": {
            "milvus": {
                "exists": True,
                "person_ids": ["P114", "P314"],
                "is_graph_built": True,
            },
            "neo4j": {"content_count": 1},
        },
    },
    {
        "id": "case_14_supply_chain_invoice_pass",
        "title": "14. 供应链融资票据异常：疑似贸易背景不真实",
        "text": "2026年6月19日 11:30，【P115# 小微企业主O】提交供应链融资申请 320 万元，核心企业确权文件与发票开具日期不一致，应收账款回款方刚成立15天，物流单号无法核验，疑似虚假贸易背景和票据套利。",
        "expect": [
            "命中 供应链融资 / 虚假贸易 / 票据套利 / 应收账款 等关键词",
            "进入贷中合规与授信风险分析",
            "输出需要人工核验的贸易证据链",
        ],
        "expect_state": {
            "milvus": {
                "exists": True,
                "person_ids": ["P115"],
                "is_graph_built": True,
            },
            "neo4j": {"content_count": 1},
        },
    },
    {
        "id": "case_15_crypto_offramp_network_pass",
        "title": "15. 虚拟币出入金网络扩散：疑似洗钱通道",
        "text": "2026年6月20日 20:05，【P116# 客户P】、【P117# 客户Q】和【P118# 客户R】先后向同一场外交易商户转入资金，商户随后拆分出金至5个银行卡账户。交易备注为空，资金停留时间不足3分钟，疑似虚拟币场外出入金和洗钱通道。",
        "expect": [
            "命中 虚拟币 / 场外交易 / 出金 / 洗钱通道 等关键词",
            "覆盖多人、多账户、同一商户的资金网络",
            "用于观察图谱聚合与相似事件召回",
        ],
        "expect_state": {
            "milvus": {
                "exists": True,
                "person_ids": ["P116", "P117", "P118"],
                "is_graph_built": True,
            },
            "neo4j": {"content_count_at_most": 1, "no_duplicate_content": True},
        },
    },
]


def _index_cases(cases: list[DemoCase]) -> dict[str, DemoCase]:
    indexed: dict[str, DemoCase] = {}
    duplicates: list[str] = []
    for case in cases:
        case_id = str(case["id"])
        if case_id in indexed:
            duplicates.append(case_id)
        indexed[case_id] = case
    if duplicates:
        raise ValueError("duplicate demo case ids: " + ", ".join(sorted(duplicates)))
    return indexed


CASES_BY_ID: dict[str, DemoCase] = _index_cases(TEST_CASES)
