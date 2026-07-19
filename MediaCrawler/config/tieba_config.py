# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/config/tieba_config.py
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

# Tieba platform configuration

# Specify Tieba ID list
TIEBA_SPECIFIED_ID_LIST = []

# 订阅源清单（P0 订阅式爬取）：`--type creator` 时按吧增量盯梢这些吧
# （列表页直存 + 追平停止 + 页上限，见 media_platform/tieba/core.subscribe_tieba_boards）。
# ⚠️ 关键词搜索（--type search）不再联动此清单（上游的隐式详情页大爬已切断）。
TIEBA_NAME_LIST = [
    "中山大学",
]

# 订阅每源每轮翻页上限（首轮冷启动的刹车——中山大学吧存量 345 万帖，绝不全吞；
# 之后每轮靠"整页无新帖=追平"提前停，通常 1~2 页收工）
TIEBA_SUB_MAX_PAGES = 10

# Specify Tieba user URL list
TIEBA_CREATOR_URL_LIST = [
    "https://tieba.baidu.com/home/main/?id=tb.1.7f139e2e.6CyEwxu3VJruH_-QqpCi6g&fr=frs",
    # ........................
]
