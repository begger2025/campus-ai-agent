# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tests/test_topic_scope.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#
# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

from tools.topic_scope import compose_topic_keyword, is_marketing_noise, matches_topic

TERMS = ["中山大学", "中大", "sysu", "逸仙"]

NEGATIVE_TERMS = ["留学中介", "保研辅导", "代写", "驾校报名"]
RESCUE_TERMS = ["投诉", "维权", "避雷", "被骗"]


class TestComposeTopicKeyword:
    def test_prepends_qualifier(self):
        assert compose_topic_keyword("宿舍空调", "中山大学", TERMS) == "中山大学 宿舍空调"

    def test_skips_when_already_contains_a_term(self):
        assert compose_topic_keyword("中山大学宿舍搬迁", "中山大学", TERMS) == "中山大学宿舍搬迁"
        assert compose_topic_keyword("中大食堂", "中山大学", TERMS) == "中大食堂"
        assert compose_topic_keyword("SYSU 选课", "中山大学", TERMS) == "SYSU 选课"  # 大小写不敏感

    def test_empty_qualifier_passthrough(self):
        assert compose_topic_keyword("宿舍空调", "", TERMS) == "宿舍空调"
        assert compose_topic_keyword("宿舍空调", None, TERMS) == "宿舍空调"

    def test_strips_whitespace(self):
        assert compose_topic_keyword("  宿舍空调 ", " 中山大学 ", TERMS) == "中山大学 宿舍空调"


class TestMatchesTopic:
    def test_hit_in_any_text(self):
        assert matches_topic(["无关标题", "正文提到中山大学的事"], TERMS)
        assert matches_topic(["逸仙时空经典帖"], TERMS)

    def test_latin_case_insensitive(self):
        assert matches_topic(["My life at SYSU"], TERMS)

    def test_no_hit(self):
        assert not matches_topic(["华南理工大学宿舍", "食堂涨价"], TERMS)

    def test_empty_terms_keeps_everything(self):
        assert matches_topic(["随便什么"], [])

    def test_none_and_empty_texts_tolerated(self):
        assert not matches_topic([None, "", "  "], TERMS)
        assert not matches_topic([], TERMS)


class TestIsMarketingNoise:
    def test_negative_hit_without_rescue_is_noise(self):
        assert is_marketing_noise(["中山大学保研辅导一对一", "名师带你上岸"], NEGATIVE_TERMS, RESCUE_TERMS)

    def test_rescue_term_keeps_content(self):
        # 投诉这些机构本身是真舆情：任一文本命中救回词就不过滤
        assert not is_marketing_noise(["中山大学保研辅导", "被骗了三千块求助"], NEGATIVE_TERMS, RESCUE_TERMS)
        assert not is_marketing_noise(["避雷某留学中介"], NEGATIVE_TERMS, RESCUE_TERMS)

    def test_no_negative_hit_passthrough(self):
        assert not is_marketing_noise(["中山大学宿舍搬迁通知"], NEGATIVE_TERMS, RESCUE_TERMS)

    def test_empty_negative_terms_passthrough(self):
        assert not is_marketing_noise(["中山大学保研辅导"], [], RESCUE_TERMS)
        assert not is_marketing_noise(["中山大学保研辅导"], None, RESCUE_TERMS)

    def test_none_and_empty_texts_tolerated(self):
        assert not is_marketing_noise([None, "", "  "], NEGATIVE_TERMS, RESCUE_TERMS)
        assert not is_marketing_noise([], NEGATIVE_TERMS, RESCUE_TERMS)

    def test_case_insensitive_substring(self):
        assert is_marketing_noise(["SYSU 代写 essay"], ["代写"], RESCUE_TERMS)

    def test_none_rescue_terms_tolerated(self):
        assert is_marketing_noise(["驾校报名优惠"], NEGATIVE_TERMS, None)
