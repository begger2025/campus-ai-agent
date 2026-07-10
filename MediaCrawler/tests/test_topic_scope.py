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

import config
from tools.topic_scope import (
    compose_topic_keyword,
    is_broad_keyword,
    is_marketing_noise,
    matches_topic,
)

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


class TestNegativeFilterConfigLists:
    """用真实配置词表验证：救回词须同时覆盖投诉类与求助类语气。"""

    def test_help_seeking_content_is_rescued(self):
        # 学生求助是真实需求信号，不是营销噪声
        assert not is_marketing_noise(
            ["有没有靠谱的考研机构求推荐"],
            config.TOPIC_NEGATIVE_TERMS,
            config.TOPIC_NEGATIVE_RESCUE_TERMS,
        )

    def test_complaint_content_is_rescued(self):
        assert not is_marketing_noise(
            ["曝光某留学中介乱收费"],
            config.TOPIC_NEGATIVE_TERMS,
            config.TOPIC_NEGATIVE_RESCUE_TERMS,
        )

    def test_pure_marketing_still_filtered(self):
        assert is_marketing_noise(
            ["考研机构春季班火热报名"],
            config.TOPIC_NEGATIVE_TERMS,
            config.TOPIC_NEGATIVE_RESCUE_TERMS,
        )

    def test_realestate_b2b_ad_is_filtered(self):
        # 蹭校名的地产/家居 B 端营销长文（实测漏网样本：床垫集采广告）应被拦
        assert is_marketing_noise(
            [
                "酒店/地产/床垫集采避坑：越来越多招标方指定慕思工程，"
                "事业单位宿舍改造、地产精装交付按总拥有成本核算，"
                "工程采购认准源头供应商，中山大学深圳校区等4000+项目同款"
            ],
            config.TOPIC_NEGATIVE_TERMS,
            config.TOPIC_NEGATIVE_RESCUE_TERMS,
        )

    def test_genuine_dorm_tender_question_not_over_filtered(self):
        # 真实学生帖含"招标"但非"招标方"，不应被误杀（刻意用招标方而非招标）
        assert not is_marketing_noise(
            ["中山大学东校区宿舍空调招标结果什么时候出"],
            config.TOPIC_NEGATIVE_TERMS,
            config.TOPIC_NEGATIVE_RESCUE_TERMS,
        )


class TestIsBroadKeyword:
    def test_equals_qualifier(self):
        assert is_broad_keyword("中山大学", "中山大学", TERMS)
        assert is_broad_keyword("  中山大学 ", "中山大学", TERMS)

    def test_equals_any_relevance_term(self):
        assert is_broad_keyword("中大", "中山大学", TERMS)
        assert is_broad_keyword("SYSU", "中山大学", TERMS)  # 大小写不敏感

    def test_whole_word_equality_not_substring(self):
        # 整词相等而非子串：含相关词的具体词不算宽泛词
        assert not is_broad_keyword("中山大学宿舍搬迁", "中山大学", TERMS)
        assert not is_broad_keyword("中大食堂", "中山大学", TERMS)

    def test_specific_keyword_passthrough(self):
        assert not is_broad_keyword("宿舍空调", "中山大学", TERMS)

    def test_empty_inputs_tolerated(self):
        assert not is_broad_keyword("", "中山大学", TERMS)
        assert not is_broad_keyword(None, "中山大学", TERMS)
        assert not is_broad_keyword("宿舍空调", "", None)

    def test_matches_qualifier_even_without_terms(self):
        assert is_broad_keyword("中山大学", "中山大学", None)
