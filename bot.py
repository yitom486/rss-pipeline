"""审核机器人（常驻，长轮询）：处理 ✅通过 / ❌丢弃 / 🔍深入了解 按钮。"""
import sys
import time
import traceback
import db
import telegram
import translate
import material
import pipeline
import agent
import cc
import config


def handle_callback(cb):
    data = cb.get("data", "")
    cb_id = cb["id"]
    msg = cb.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    message_id = msg.get("message_id")
    text = msg.get("text", "")

    if ":" not in data:
        telegram.answer_callback(cb_id)
        return
    action, sid = data.split(":", 1)
    try:
        item_id = int(sid)
    except ValueError:
        telegram.answer_callback(cb_id)
        return

    with db.conn() as c:
        item = db.get_item(c, item_id)
        if not item:
            telegram.answer_callback(cb_id, "条目不存在")
            return

        if action == "approve":
            db.set_status(c, item_id, "published"); c.commit()
            telegram.edit_message(chat_id, message_id, text + "\n\n✅ *已通过发布*")
            telegram.answer_callback(cb_id, "已通过，标记为发布")

        elif action == "discard":
            db.set_status(c, item_id, "discarded"); c.commit()
            telegram.edit_message(chat_id, message_id, text + "\n\n❌ *已丢弃*")
            telegram.answer_callback(cb_id, "已丢弃")

        elif action == "dive":
            telegram.answer_callback(cb_id, "正在深入分析，请稍候…")
            header = f"🔍 深入了解：**{item['zh_title']}**\n\n"
            try:
                mat = material.fetch_material(item["url"])
                chunks = translate.deep_dive_stream(item["title"], item["url"], mat)
                # 流式打字机：边生成边编辑，结束后 HTML 定稿
                telegram.stream_to_message(chunks, header=header)
                telegram.send_message(f"原文：{item['url']}", markdown=False)
            except Exception as e:
                telegram.send_message(f"分析失败：{e}", markdown=False)
        else:
            telegram.answer_callback(cb_id)


def main():
    db.init()
    print("审核机器人启动，开始长轮询…", flush=True)
    offset = None
    while True:
        try:
            updates = telegram.get_updates(offset=offset, timeout=50)
        except Exception as e:
            print(f"[警告] getUpdates 出错: {e}", file=sys.stderr, flush=True)
            time.sleep(5)
            continue
        for u in updates:
            offset = u["update_id"] + 1
            # 鉴权：只放行配置里的 chat_id，其他人一律忽略
            who = None
            if "callback_query" in u:
                who = str(u["callback_query"].get("from", {}).get("id", ""))
            elif "message" in u:
                who = str(u["message"].get("chat", {}).get("id", ""))
            if config.TELEGRAM_CHAT_ID and who and who != str(config.TELEGRAM_CHAT_ID):
                continue
            try:
                if "callback_query" in u:
                    handle_callback(u["callback_query"])
                elif "message" in u:
                    t = (u["message"].get("text") or "").strip()
                    if not t:
                        continue
                    if t == "/start":
                        telegram.send_message(
                            "👋 审核机器人在线。\n"
                            "· 直接发文字 = 流水线查询（DeepSeek，便宜）\n"
                            "  例：现在抓一遍最新热点 / 还有哪些没审核的 / 深入了解 #5\n"
                            "· /cc <任务> = 让 Claude Code 干活（通用能力，A档限工具+限目录）\n"
                            "  例：/cc 把 agent-workspace 里的 notes.md 整理成提纲"
                        )
                    elif t.startswith("/cc"):
                        task = t[3:].strip()
                        if not task:
                            telegram.send_message("用法：/cc <要让 Claude Code 做的事>", markdown=False)
                        else:
                            telegram.send_message("🤖 Claude Code 处理中，请稍候…", markdown=False)
                            try:
                                out = cc.run(task)
                            except Exception as e:
                                out = f"出错：{e}"
                            # 输出可能很长，截断到 Telegram 单条上限内
                            telegram.send_message(out[:3800], markdown=False)
                    else:
                        # 自然语言指令交给 agent（只读+取材白名单工具），流式作答
                        try:
                            telegram.stream_to_message(agent.handle_stream(t))
                        except Exception as e:
                            telegram.send_html(f"处理出错：{e}")
            except Exception:
                traceback.print_exc()


if __name__ == "__main__":
    main()
