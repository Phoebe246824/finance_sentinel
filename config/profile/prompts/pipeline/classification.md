对银行零售风控事件进行分类，并提取结构化的关键实体分组。

Classify the event into the most relevant configured category. Use category keyword extensions as weak signals, not as the only evidence. When the text is ambiguous, choose the default event type and explain the uncertainty in the summary. The summary should be concise, neutral, and anchored to observable facts. The summary 必须是一句话金融风控摘要，包含主体、资金行为、关键风险信号和建议动作。

Configured categories:
{category_options}

Default event type: {default_event_type}
Summary instruction: {summary_instruction}

key_entities 提取要求：按以下九组分组输出——
customer_ids、account_ids、merchant_ids、devices、amounts、counterparties、risk_signals、transaction_times、recommended_actions。
重点关注：接近阈值的多笔转账、新开户账户、虚拟币/保证金/涉诈账户、首次设备或境外 IP、短信验证码失败、贷款包装流水、多客户向同一账户归集、投诉与拒绝提现、冻结/复核/止付建议。
不要提取中性物品、无关人物、主观情绪、背景常识。

Title: {title}
Content: {raw_content}

{output_schema}
