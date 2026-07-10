# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/config/zhihu_config.py
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


# Zhihu platform configuration

# 搜索结果排序方式（media_platform/zhihu/field.py SearchSort 的 value）：
# "" = 综合排序（默认） | "upvoted_count" = 最多赞同 | "created_time" = 最新发布
# --fresh yes 会覆盖为 "created_time"（时间倒序使窗口整页早停可用）
ZHIHU_SEARCH_SORT = ""

# Specify Zhihu user URL list
ZHIHU_CREATOR_URL_LIST = [
    "https://www.zhihu.com/people/yd1234567",
    # ........................
]

# Specify Zhihu ID list
ZHIHU_SPECIFIED_ID_LIST = [
    "https://www.zhihu.com/question/826896610/answer/4885821440",  # answer
    "https://zhuanlan.zhihu.com/p/673461588",  # article
    "https://www.zhihu.com/zvideo/1539542068422144000",  # video
]
