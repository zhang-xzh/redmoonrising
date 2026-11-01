"""Write res/common/messages.zh.txt for the EVE 3913 client.

The client loads res:/common/messages.txt first and then, when
prefs.languageID is set, res:/common/messages.<lang>.txt on top of it
(cfg.py/__LoadStaticData).  The language file is UTF-16LE with a BOM and
CRLF line endings, exactly like the retail messages.ru.txt / .ja.txt /
.ko.txt files.

Keys below are the login/download UI text from messages.txt (UI_LOGIN_*)
plus the can-do messages the client needs before the server sends its own
message table.
"""
import argparse
import io
import os
import shutil

LINES = [
    ("ReleaseTitle", "EVE Online"),
    ("ReleaseSubtitle", "Red Moon Rising"),
    ("UI_LOGIN_USERNAME", "用户名"),
    ("UI_LOGIN_PASSWORD", "密码"),
    ("UI_LOGIN_SERVER", "服务器"),
    ("UI_LOGIN_SCROLLTOBOTTOM", "<center>滚动到底部继续"),
    ("UI_LOGIN_SUPPORT", "客服支持"),
    ("UI_LOGIN_NEWS", "新闻"),
    ("UI_LOGIN_PATCHINFO", "补丁信息"),
    ("UI_LOGIN_EULA", "用户协议"),
    ("UI_LOGIN_ACCOUNTMGMT", "账号管理"),
    ("UI_LOGIN_CREATEACCOUNT", "创建账号"),
    ("UI_LOGIN_SHOWINTROMOVIE", "播放介绍影片"),
    ("UI_LOGIN_CONNECT", "连接"),
    ("UI_LOGIN_VERSION", "版本"),
    ("UI_LOGIN_STATUS", "状态"),
    ("UI_LOGIN_PLAYERS", "玩家"),
    ("UI_LOGIN_CHECKINGSTATUS", "正在检查状态..."),
    ("UI_LOGIN_PORT", "端口 "),
    ("UI_LOGIN_INVALIDPORTNUMBER", "端口号无效"),
    ("UI_LOGIN_UNABLETOGETSERVERSTATUS", "无法在 26000 以外的端口获取服务器状态"),
    ("UI_LOGIN_SERVERFAQ", "服务器常见问题"),
    ("UI_LOGIN_INCOMPATIBLE", "不兼容"),
    ("UI_LOGIN_UNABLETOCONNECTTO", "无法连接到 %(ip)s 的 %(port)s 端口"),
    ("UI_LOGIN_PLEASESELECTASERVER",
     "请选择服务器<br>如果不知道选择哪台服务器<br>请选择 \"随机服务器\"。"),
    ("UI_LOGIN_SELECTSERVER", "选择服务器"),
    ("UI_LOGIN_PATCHPROGRESS", "已读取 %(currentBytes)d%%，共 %(totalBytes)d KB"),
    ("UI_CHARSEL_ENTERGAME", "进入游戏"),
    ("UI_CHARSEL_TERMINATE", "删除角色"),
    ("UI_CHARSEL_CREATENEWCHARACTER", "创建新角色"),
    ("UI_CHARSEL_COMPLETETERMINATION", "完成销毁"),
    ("UI_CHARSEL_ABORTTERMINATION", "取消销毁"),
    ("UI_CHARSEL_SELECTORCREATECHARACTER", "选择或创建角色"),
    ("UI_CHARSEL_SELECTCHARACTER", "选择角色"),
    ("UI_CHARSEL_CREATECHARACTER", "创建角色"),
    ("UI_CHARSEL_BOUNTY", "赏金"),
    ("UI_CHARSEL_MEMBERINFO", "已成为 %(corpname)s 军团 [%(ticker)s] 成员 %(corpage)s"),
    ("UI_GENERIC_EMPTY", "空"),
    ("UI_GENERIC_LOCATION", "位置"),
    ("UI_GENERIC_CONSTELLATION", "星座"),
    ("UI_GENERIC_REGION", "星域"),
    ("UI_GENERIC_SECURITYSTATUS", "安全等级"),
    ("UI_GENERIC_WEALTH", "财富"),
    ("UI_LOAD_LOADING", "载入中"),
    ("UI_LOAD_GETTINGCHARACTERS", "正在获取角色"),
    ("UI_LOAD_DONEETTINGCHARACTERS", "已获取角色"),
    ("UI_LOAD_DOWNLOADINGPATCH", "正在下载补丁 "),
    ("UI_LOAD_PATCHDOWNLOADED", "补丁已下载"),
    ("MlsNotifyCaveats.infomodal",
     "语言选择::您选择的语言尚未提供全部文本。<br>若某项翻译缺失，将显示英文。"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", default=r"M:\EVE-LOCAL\inputs\EVE-Online-3913",
                    help="client root containing res/common")
    a = ap.parse_args()
    out = os.path.join(a.client, "res", "common", "messages.zh.txt")
    if not os.path.exists(out + ".orig"):
        shutil.copyfile(out, out + ".orig")
    text = "".join("%s=%s\r\n" % (k, v) for (k, v) in LINES)
    io.open(out, "wb").write(b"\xff\xfe" + text.encode("utf-16-le"))
    print("wrote %s (%d bytes)" % (out, os.path.getsize(out)))


if __name__ == "__main__":
    main()
