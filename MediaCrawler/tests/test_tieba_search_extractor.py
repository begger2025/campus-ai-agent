from media_platform.tieba.help import (
    EMPTY_VERDICT_BLOCKED,
    EMPTY_VERDICT_NO_RESULT,
    EMPTY_VERDICT_PARSER_MISMATCH,
    TieBaExtractor,
    classify_empty_search_page,
)


def test_extract_search_note_list_supports_current_search_cards():
    html = """
    <div class="threadcardclass thread-new3 index-feed-cards">
      <div class="thread-content-box">
        <div class="display-flex thread-card-top">
          <div class="thread-forum-name display-flex align-center">
            <a href="https://tieba.baidu.com/f?kw=%E4%B8%AD%E5%B1%B1%E5%A4%A7%E5%AD%A6">
              <div class="forum-name">中山大学 吧</div>
            </a>
          </div>
          <div class="top-title">
            <a class="attention-wrap" href="/home/main?id=abc">寒窗椿雪</a>
            <span> 发布于 2026-5-23</span>
          </div>
        </div>
        <a href="https://tieba.baidu.com/p/10737689970?fr=undefined">
          <div class="title-content-wrap">
            <div class="title-wrap">我们 中山大学 ...究竟会变成什么样子...</div>
            <div class="abstract-wrap">灯没了</div>
          </div>
        </a>
      </div>
    </div>
    """

    notes = TieBaExtractor.extract_search_note_list(html)

    assert len(notes) == 1
    assert notes[0].note_id == "10737689970"
    assert notes[0].title == "我们 中山大学 ...究竟会变成什么样子..."
    assert notes[0].desc == "灯没了"
    assert notes[0].tieba_name == "中山大学"
    assert notes[0].publish_time == "2026-5-23"
    assert notes[0].user_nickname == "寒窗椿雪"


# ===== 空搜索页三分类（老排障文档 §3.5/§9.4 的真实场景固化成用例）=====

def test_classify_blocked_page_with_failure_banner():
    # §3.5 实测：被风控的页面同时含"数据加载失败"和"木有找到"，且正文无关键词——
    # 风控文案优先于无结果文案
    html = "<html><body>数据加载失败，请稍后重试 哎呀！木有找到相关内容 大家都在逛的吧</body></html>"
    assert classify_empty_search_page(html, "中山大学 食堂") == EMPTY_VERDICT_BLOCKED


def test_classify_blocked_page_when_keyword_absent():
    # 无风控文案、无结果文案，但正文连关键词都不含：搜索数据没加载
    html = "<html><body>大家都在逛的吧 推荐内容</body></html>"
    assert classify_empty_search_page(html, "中山大学 食堂") == EMPTY_VERDICT_BLOCKED


def test_classify_genuine_no_result():
    html = "<html><body>中山大学 食堂 的搜索结果：哎呀！木有找到相关内容</body></html>"
    assert classify_empty_search_page(html, "中山大学 食堂") == EMPTY_VERDICT_NO_RESULT


def test_classify_no_result_when_keyword_echoed_without_markers():
    # 关键词在场、无任何异常文案：按正常无结果处理（保守，不误报风控）
    html = "<html><body>搜索 中山大学 食堂 <div>0 条结果</div></body></html>"
    assert classify_empty_search_page(html, "中山大学 食堂") == EMPTY_VERDICT_NO_RESULT


def test_classify_parser_mismatch_when_cards_present():
    # 页面存在帖子卡片结构 + 帖子链接，但解析器抽出 0 条：DOM 变化
    html = '<div class="threadcardclass new-variant"><a href="/p/123456">帖子</a></div>'
    assert classify_empty_search_page(html, "中山大学 食堂") == EMPTY_VERDICT_PARSER_MISMATCH


def test_classify_ignores_card_marker_inside_script_text():
    # "s_post" 出现在脚本字符串里不算卡片（结构性判定），正文无关键词 → 风控
    html = '<script>var legacy = "s_post";</script><body>大家都在逛的吧</body>'
    assert classify_empty_search_page(html, "中山大学 食堂") == EMPTY_VERDICT_BLOCKED


def test_extract_note_detail_missing_reply_nodes_does_not_crash():
    # §3.3：新版详情页缺 l_reply_num 节点，旧代码 list index out of range 崩整帖；
    # 现在应回退空串并正常返回
    html = """
    <html><head><title>某帖标题</title>
      <meta name="description" content="正文摘要" /></head>
      <body>
        <a id="lzonly_cntn" href="/p/998877?see_lz=1"></a>
        <div class="p_postlist"></div>
      </body></html>
    """
    note = TieBaExtractor().extract_note_detail(html)
    assert note.note_id == "998877"
    assert note.total_replay_num == 0
    assert note.total_replay_page == 0
