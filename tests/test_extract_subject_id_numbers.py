"""测试 extract_subject_id_numbers 人员 ID 提取逻辑。"""

from sentinel.utils.text import extract_person_id_numbers, extract_subject_id_numbers


class TestExtractSubjectIdNumbers:
    def test_bracket_format_single(self):
        """【P01# 小明】格式应提取 P01。"""
        assert extract_subject_id_numbers("【P01# 小明】被发现") == ["P01"]

    def test_bracket_format_multiple(self):
        """多个【编号# 名称】应全部提取。"""
        text = "【P01# 小明】和【C009# 启航中心】有关联，【P02# 张三】也参与"
        result = extract_subject_id_numbers(text)
        assert sorted(result) == ["C009", "P01", "P02"]

    def test_bracket_format_with_spaces(self):
        """方括号内有多余空格应正常处理。"""
        assert extract_subject_id_numbers("【 P01 # 小明 】") == ["P01"]

    def test_plain_id_format(self):
        """纯 ID 格式（无方括号）应提取。"""
        assert extract_subject_id_numbers("账户 P01 和 T002 有交易") == ["P01", "T002"]

    def test_deduplication(self):
        """同一 ID 出现多次应去重。"""
        text = "P01 和 P01 有关联，【P01# 小明】也在场"
        assert extract_subject_id_numbers(text) == ["P01"]

    def test_case_insensitive(self):
        """小写 id 应统一转为大写。"""
        assert extract_subject_id_numbers("p01 和 P01 是同一人") == ["P01"]

    def test_no_ids(self):
        """文本中无 ID 应返回空列表。"""
        assert extract_subject_id_numbers("今天天气很好") == []

    def test_empty_string(self):
        """空字符串应返回空列表。"""
        assert extract_subject_id_numbers("") == []

    def test_mixed_bracket_and_plain(self):
        """方括号格式优先，纯 ID 格式补充。"""
        text = "【P01# 小明】和 P02 有联系"
        result = extract_subject_id_numbers(text)
        assert sorted(result) == ["P01", "P02"]

    def test_bracket_takes_priority(self):
        """方括号中的 P01 和后面的纯 P01 应合并。"""
        text = "【P01# 小明】和 P01 是同一个人"
        result = extract_subject_id_numbers(text)
        assert result == ["P01"]

    def test_extract_person_ids_only_returns_p_prefix(self):
        """仅人员提取函数不应返回地点/机构/交易等非人员编号。"""
        text = "【L17# 北京市海淀区】、【C11# 清河街道办事处】、【P01# 张三】、T002"
        result = extract_person_id_numbers(text)
        assert result == ["P01"]


def test_sanitize_text_input_removes_zero_width_and_control_chars():
    from sentinel.utils.text import sanitize_text_input

    assert sanitize_text_input("A\u200bB\x00C\nD") == "ABC\nD"


def test_parse_llm_json_object_accepts_fenced_json():
    from sentinel.utils.text import parse_llm_json_object

    assert parse_llm_json_object('```json\n{"ok": true}\n```') == {"ok": True}


def test_parse_llm_json_object_extracts_embedded_object():
    from sentinel.utils.text import parse_llm_json_object

    assert parse_llm_json_object('prefix {"risk_score": 0.8} suffix') == {
        "risk_score": 0.8
    }
