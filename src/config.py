"""常量与 URL 模板。

数据来源（球探体育 titan007）：
- 竞彩赛事列表：``jc.titan007.com/xml/odds_jc.txt``（GBK），每行一场，含 ScheduleID 与竞彩胜平负赔率。
- 单场百家欧指明细：``1x2d.titan007.com/{match_id}.js``（UTF-8），``game`` 数组含各公司初盘/即时赔率、去水概率、凯利。
"""
from __future__ import annotations

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# 竞彩足球当日赛事列表（GBK 编码），含 ScheduleID 与竞彩胜平负赔率。
# 注意：该文件按写入顺序排列，与官方「周X00N」编号可能存在偏移（如前几条
# 可能是已开赛/非足彩场次），因此不应直接按序号索引对应官方编号。
JC_SCHEDULE_URL = "https://jc.titan007.com/xml/odds_jc.txt"

# 竞彩足球官方比分/赛程列表（UTF-8 编码）。这是 jc.titan007.com 首页/schedule.aspx
# 实际使用的数据源，每条记录自带「周X00N」官方编号、对阵、联赛等信息，
# 与用户在竞彩官网/截图中看到的场次号一致。用于把「周六011」等映射到正确 ScheduleID。
BF_JC_URL = "https://jc.titan007.com/xml/bf_jc.txt"

# 按指定日期获取竞彩赛事列表/赛果（GBK 编码）。
# 站点 schedule.aspx?d=日期 内部通过该接口加载历史/指定日期的赛事；
# 注意：该接口返回的「开赛时间」字段存在 -1 个月的显示偏移，
# 真实开赛时间请以单场欧指 JS（1x2d.titan007.com/{id}.js）的 MatchTime 为准。
JC_RESULT_URL = "https://jc.titan007.com/handle/JcResult.aspx?d={date}"

# 单场百家欧指数据 JS（UTF-8 编码，含 game 数组）
ODDS_JS_URL = "https://1x2d.titan007.com/{match_id}.js"

# 欧指列表页（仅用于 Referer，真实数据在上面的 JS 文件里）
ODDS_LIST_PAGE = "https://op1.titan007.com/oddslist/{match_id}.htm"

# 足球亚洲盘(让球)盘口页（HTML 表格，UTF-8）。按 ScheduleID 取。
#   例：2929718 -> https://vip.titan007.com/AsianOdds_n.aspx?id=2929718&l=0
# 该页以 HTML 表格展示各公司让球盘口：初盘 + 即时(oddstype=wholeLastOdds) +
# 终盘(oddstype=wholeOdds，隐藏)。每行 goals 属性直接给出数值让球（主队视角，负=客让）。
# 与篮球亚盘同理，优先取终盘(wholeOdds)以反映赛前封盘，缺失时回退即时盘。
FOOTBALL_ASIAN_URL_TMPL = "https://vip.titan007.com/AsianOdds_n.aspx?id={match_id}&l=0"

# game 数组中「竞彩官*」行的判定关键字
LOTTERY_KEYWORDS = ("竞彩官", "Lottery Official")

# 输出方向中文标签
OUTCOME_LABELS = ("主胜", "平局", "客胜")

# ---------------------------------------------------------------------------
# 篮球（NBA / 竞彩篮球）胜负(moneyline)数据
# ---------------------------------------------------------------------------
# 单场胜负数据 JS（UTF-8）。URL 路径由 ScheduleID 派生：{id[0]}/{id[1:3]}/{id}.js
#   例：705225 -> https://nba.titan007.com/1x2/data1x2/7/05/705225.js
# 注：titan007 公共端点仅暴露篮球「胜负」数据；「让分/大小分」位于内部服务器
#     （111_server.titan007.com:1111），公网不可达，本工具暂不支持。
NBA_1X2_JS_TMPL = "https://nba.titan007.com/1x2/data1x2/{a}/{b}/{match_id}.js"

# 胜负列表页（仅用于 Referer）
NBA_ODDS_LIST_PAGE = "https://nba.titan007.com/1x2/oddslist/{match_id}.htm"

# 当日竞彩篮球赛事列表（UTF-8）。这是竞彩官方开售的篮球胜负场次，
# 仅含竞彩开售场次（非 titan007 全量篮球），编号从 周六301 起。
# 每行/段以 `!` 分隔；首段联赛前缀后用 `$ScheduleID` 标记单场，
# 字段中含竞彩场次号标签（如 `周六301`）与对阵。
NBA_LOTTERY_LIST_URL = "https://jc.titan007.com/xml/bf_jc_lq.txt"

# 篮球历史/指定日期竞彩赛事。与足球共用 JcResult，加 `st=2` 参数；
# 该接口返回当日全部竞彩（足球+篮球混合），需按联赛筛选「篮球」场次。
# 注意：竞彩统一编号中足球/篮球混用，编号段因日而异（例如 2026-08-28
# 周五301~310 全为篮球：301~302 世亚预、303~306 世欧预、307~310 WNBA）；
# 历史查询按「联赛名含篮/NBA/WNBA + 已知篮球联赛 ID 白名单」筛选篮球场次。
NBA_HISTORY_URL_TMPL = "https://jc.titan007.com/handle/JcResult.aspx?d={date}&st=2"

# 单场篮球让分(亚洲盘)盘口页（HTML 表格，UTF-8）。按 ScheduleID 取。
#   例：705225 -> https://nba.titan007.com/odds/AsianOdds_n.aspx?id=705225&l=0
# 该页以 HTML 表格展示各公司让分盘口（初盘/即时 上盘赔率、让分数、下盘赔率），
# 全部以香港盘(水位)显示。竞彩官* 行亦在亚盘格式下显示，故统一用 HK 惯例去水。
NBA_SPREAD_URL_TMPL = "https://nba.titan007.com/odds/AsianOdds_n.aspx?id={match_id}&l=0"

# 篮球胜负方向中文标签（2-way，无平局）
NBA_OUTCOME_LABELS = ("主胜", "客胜")
