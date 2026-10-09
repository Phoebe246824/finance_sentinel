"""
Sentinel 黑名单 + Milvus 事件库系统 — 单元测试
=========================================
测试范围:
    - src/sentinel/utils/text.py: extract_subject_id_numbers()
    - src/sentinel/blacklist/filter.py: BlacklistFilter 三合一 OR 匹配
    - src/sentinel/blacklist/milvus_stash.py: Milvus 事件库/回捞/标记已构图
    - src/sentinel/blacklist/stores/*.py: Milvus 黑名单存储
"""
