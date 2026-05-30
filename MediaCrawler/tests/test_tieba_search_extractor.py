from media_platform.tieba.help import TieBaExtractor


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
