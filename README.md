# 足球 / 篮球 赔率分析工具（titan007 百家数据 → 概率 + 体彩方向）

从球探体育 titan007 抓取单场比赛的**百家赔率**，过滤清洗后估算市场共识概率，
并结合**体彩官方赔率**给出体彩投资方向的相对价值研判。

- **足球**：胜 / 平 / 负（欧指）方向分析。
- **篮球**：胜 / 负（moneyline）方向分析（见下方「篮球胜负分析」）。

> ⚠️ 本工具仅做基于公开赔率的概率与价值量化，**不构成任何赛果预测或投资建议**。博彩有风险，请理性投注。

## 数据来源

| 用途 | 接口 | 编码 |
|------|------|------|
| 当日竞彩赛事列表 | `jc.titan007.com/xml/odds_jc.txt` | GBK |
| **指定日期（含历史）赛事列表** | `jc.titan007.com/handle/JcResult.aspx?d=YYYY-MM-DD` | UTF-8 |
| 单场百家欧指明细 | `1x2d.titan007.com/{match_id}.js` | UTF-8 |

## 安装

```bash
# 核心依赖（main.py 分析路径必需）；typer 仅 analyze 子命令需要
pip install -r requirements.txt
# 或最小安装：pip install httpx
```

> 在 PyCharm 中直接运行 `main.py`：分析 / list / first 只需 `httpx`，
> 无需安装 `typer`；只有显式用 `analyze` 子命令时才需要 `typer`。

## 使用

最简单：直接运行 `main.py`，无需模块调用。

```bash
python main.py                 # 分析当日竞彩第一场（双击即可看结果）
python main.py 3000426         # 分析指定比赛 ID
python main.py 周六015          # 按「星期+序号」定位比赛（当天：周六第 15 场）
python main.py 周五001          # 分析历史比赛：自动取「最近一个周五」的 001（如昨天周五）
python main.py 015             # 按序号定位比赛（当日列表）
python main.py <oddslist链接>  # 从链接自动提取 ID 并分析
python main.py list            # 列出当日竞彩赛事
python main.py list 2026-08-28 # 列出指定日期的赛事（含 周五001 等标签，便于核对）
python main.py first           # 等价于无参数（当日第一场）
python main.py gui             # 图形弹窗输入（推荐：输入 周六015 / 周五001 后自动分析）
python main.py analyze 3000426 --json   # CLI 子命令一致（可加 --json）
```

### 分析历史比赛（验证用）

输入「周X+序号」时，工具会按**真实日历**定位到该星期**最近一次出现**的那一天，再按标签精确匹配：

- 今天周六输入 `周六015` → 当天第 15 场。
- 今天周六输入 `周五001` → 昨天（最近一个周五）的第 1 场。
- 报告中的「开赛时间」取自单场欧指 JS（真实日期），可在弹窗底部的【验证提示】对照实际比分自行校验。

> ⚠️ 历史赛事接口 `JcResult.aspx` 返回的「开赛时间」字段存在 -1 个月的显示偏移，
> 因此判断「是哪一天」一律以单场欧指 JS 的 `MatchTime` 为准（报告已据此显示真实日期）。
> 该接口不直接提供干净的最终比分，故本工具不自动抓取赛果；验证请对照竞彩官网/比分网。

等效的模块式调用（原有方式仍可用）：

```bash
# 分析指定比赛（ScheduleID，即 oddslist URL 里的数字）
python -m src.cli analyze 3000426

# 也可直接传 oddslist 链接，自动提取 ID
python -m src.cli analyze --url https://op1.titan007.com/oddslist/3000426.htm

# 分析当日竞彩列表中的「第一场比赛」
python -m src.cli first

# 列出当日竞彩赛事，挑一场
python -m src.cli list

# JSON 输出（便于二次开发）
python -m src.cli analyze 3000426 --json
```

## 篮球胜负分析（nba 子命令）

篮球无平局，分析对象为**胜负（moneyline）**的「主胜 / 客胜」方向。用法与足球版对称：

```bash
python main.py nba                 # 分析当日篮球列表第一场
python main.py nba 705225         # 分析指定比赛 ID（如纽约自由人 VS 芝加哥天空）
python main.py nba 周六305         # 按「星期+场次号」定位（当日篮球场次号从 301 起推断）
python main.py nba 305            # 仅场次号，同样定位到列表第 5 场
python main.py nba <nba oddslist链接>  # 例：https://nba.titan007.com/1x2/oddslist/705225.htm
python main.py nba list           # 列出当日篮球赛事（含竞彩场次号与队名）
python main.py nba list 2026-08-28  # 列出指定日期的竞彩篮球（往期浏览/验证用）
python main.py nba 301            # 篮球胜负分析（默认）
python main.py nba 301 --spread   # 篮球【让分】方向概率分析
python main.py nba 301 --both     # 胜负 + 让分 一起看
python main.py nba gui            # 篮球弹窗输入（可切换 胜负/让分/两者）
python nba_gui.py                  # 篮球弹窗独立运行（双击即可，无需命令行参数）
python main.py nba 705225 --json  # JSON 输出（便于二次开发）
```

### 篮球数据来源

| 用途 | 接口 | 编码 |
|------|------|------|
| 当日**竞彩篮球**赛事列表（仅开售场次） | `jc.titan007.com/xml/bf_jc_lq.txt` | UTF-8 |
| 历史/指定日期竞彩赛事（足球+篮球混合，需筛篮球） | `jc.titan007.com/handle/JcResult.aspx?d=YYYY-MM-DD&st=2` | UTF-8 |
| 单场胜负数据明细 | `nba.titan007.com/1x2/data1x2/{id[0]}/{id[1:3]}/{id}.js` | UTF-8 |
| 单场**让分(亚洲盘)盘口** | `nba.titan007.com/odds/AsianOdds_n.aspx?id={id}&l=0`（HTML 表格） | UTF-8 |

> **关于「让分」**：已支持！titan007 的篮球让分页（`AsianOdds_n.aspx`）是公开可访问的 HTML 表格，
> 含各公司初盘/即时让分盘口（上盘赔率、让分数、下盘赔率），本工具解析后给出**主队覆盖让分的市场共识概率**。
> 注意盘口惯例：该页全部以**香港盘(水位)**显示（如 `0.83` 表示下注 1 返 1.83），去水概率用
> `1/(1+O)` 口径（非欧洲盘 `1/O`），代码已统一处理（含竞彩官*行）。
>
> **让分数据的历史可用性**：titan007 仅对**近期/当日**比赛保留让分页；较早的历史比赛让分页会返回 502，
> 此时请改用「胜负」分析做往期验证（胜负数据对历史比赛长期保留）。

### 篮球场次号说明

篮球使用**竞彩统一编号**（与足球共用同一编号池，按当日赛程排序，篮球与足球会混排）。

- 当日若只有篮球：从 `周六301` 起。
- 历史日（足球+篮球混合）：篮球的编号位置取决于当天赛程。例如 2026-08-28 当天，
  篮球世预赛占 `周五301~306`（如 周五301 = 叙利亚 VS 澳大利亚），WNBA 占 `周五307~310`。
- 输入 `周X+序号` 时按**竞彩统一编号**定位；若该编号对应篮球联赛则分析，
  若对应足球则提示「该编号对应足球场次，不是篮球」。也可直接输入比赛 ID（如 `728077`）。
- 往期浏览：`python main.py nba list 2026-08-28` 列出当日所有竞彩篮球（含竞彩场次号与队名）。

> 弹窗运行时控制台若打印 `libpng warning: iCCP: known incorrect sRGB profile`，是 Tk 库的无害
> 噪音，不影响功能，可忽略（双击用 `pythonw` 运行则不显示）。

## 网页版（Web）

不想开弹窗、想在浏览器里用？`web_app.py` 是一个**零额外依赖**的 Web 服务（仅用 Python 标准库 + 现有 `src` 模块），
功能和 `gui.py` / `nba_gui.py` 完全一致：在页面上切「足球/篮球」、输入场次、点「分析」即显示结果。

```bash
python web_app.py            # 默认端口 8000，启动后自动打开 http://localhost:8000
python web_app.py 9000       # 指定端口
```

页面功能：
- 顶部「足球 / 篮球」切换标签。
- 篮球模式额外有「胜负 / 让分 / 两者」下拉。
- 支持输入 `周六015`、`周五001`、`3000426`、`705225`、`周六301`、以及 oddslist 链接。
- 结果显示在深色代码框中，与命令行/弹窗输出一致（含历史赛果对照兜底）。

> 局域网内其他设备访问：用本机局域网 IP 替换 `localhost`（如 `http://192.168.x.x:8000`）。
> 想让手机**随时随地**访问，需把服务部署到公网，见下方「部署到公网（手机访问）」。

## 部署到公网（手机访问）

`web_app.py` 是纯 Python 标准库实现的 HTTP 服务，可一键部署到任意支持 Python 的 PaaS，
部署后手机会获得一个公网网址，随时打开即用。仓库已内置 `Procfile` / `railway.json` / `render.yaml` /
`Spacefile` / `requirements.txt` 与 `/healthz` 健康检查，开箱即用。

> **绑卡提示**：Railway / Render 免费实例现在常要求绑定信用卡做身份验证（$1 临时预授权，不会扣款）。
> 若你不想绑卡，直接用下方的 **Deta Space** 或 **Cloudflare Tunnel** 方案。

### 方式一：Railway（推荐，最简单）

1. 在 GitHub 新建一个**空仓库**，把本仓库 push 上去（见下方「推送到 GitHub」）。
2. 打开 https://railway.app → 用 GitHub 登录 → `New Project` → `Deploy from GitHub repo` → 选你的仓库。
3. Railway 自动识别 `railway.json` 安装依赖并启动；免费版即分配公网域名 `xxx.up.railway.app`。
4. 手机浏览器打开该域名即可使用。

### 方式二：Render

1. 同上先把代码 push 到 GitHub。
2. 打开 https://render.com → 用 GitHub 登录 → `New` → `Web Service` → 选仓库。
3. Render 自动读取 `render.yaml`：`plan: free`，`buildCommand` 装依赖、`startCommand` 启动服务。
4. 部署完成后获得 `xxx.onrender.com` 公网域名，手机直接打开。

### 方式三：Deta Space（无需信用卡，推荐替代）

1. 安装 Deta Space CLI（Windows PowerShell）：
   ```powershell
   iwr https://get.deta.dev/space-cli.ps1 -useb | iex
   ```
2. 打开 https://deta.space 注册/登录（邮箱即可，**无需信用卡**）。
3. 在 Deta Space 的 Teletype（底部命令栏）生成一个 Access Token，回到本机运行：
   ```bash
   space login
   ```
4. 在项目根目录运行：
   ```bash
   space new
   # 项目名可填 football-odds-analysis
   ```
5. 部署：
   ```bash
   space push
   ```
6. Deta Space 会读 `Spacefile`（Python 3.9，`python web_app.py`），安装 `requirements.txt` 后上线，
   分配 `xxx.deta.app` 公网域名。

### 方式四：Cloudflare Tunnel（本地穿透，无需信用卡）

如果你不想用任何 PaaS，可以让本地电脑常开，通过 Cloudflare 免费隧道暴露公网：

1. 本机先启动网页服务：
   ```bash
   python web_app.py
   ```
2. 下载 `cloudflared`（Windows）：https://github.com/cloudflare/cloudflared/releases
3. 在同一台机器运行：
   ```bash
   cloudflared tunnel --url http://localhost:8000
   ```
4. 命令行会输出一个 `https://xxx.trycloudflare.com` 的临时公网网址，手机即可打开。
5. 想要固定域名：到 https://dash.cloudflare.com 注册免费账号 → Zero Trust → Tunnels → Create tunnel →
   选择 Cloudflared connector，按提示在本机运行一条长期命令，即可获得固定 `https://你的域名.xxx`。

> 免费层注意：PaaS 免费实例在**一段时间无访问后会休眠**，首次打开需等待数秒冷启动；
> 持续运行需升级付费 plan。此外 titan007 数据源有频率限制，多人高频访问可能被限流。

### 推送到 GitHub

```bash
git add -A
git commit -m "feat: 竞彩赔率分析 Web 版，支持公网部署"
git branch -M main
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
```

> 若 GitHub 开启双因素认证，push 需用 Personal Access Token（Settings → Developer settings →
> PAT，勾选 `repo`）代替密码；也可配置 SSH key 后用 `git@github.com:<用户名>/<仓库名>.git`。

## 分析方法（已在 `src/analysis.py` / `src/nba_analysis.py` 实现）

1. **市场共识概率**：对各家公司的「去水隐含概率」取均值（wisdom of crowds）。
   网站给出的 `主胜率/和率/客胜率` 已是 `(1/赔率)/Σ(1/赔率)`，天然去水，直接聚合。
   另给中位数作为稳健性校验。
2. **体彩隐含概率**：用 `竞彩官*` 行的即时赔率同样去水得到。
3. **价值 edge**：`edge_i = 市场共识概率_i − 体彩隐含概率_i`（百分点）。
   `edge > 0` 表示该方向被体彩相对低估，在体彩下注有正向价值。
4. **期望收益 EV**：`EV_i = 市场共识概率_i × 体彩赔率_i − 1`。
   体彩抽水约 11%（返还率 ≈ 88%），故三项 EV 通常为负；该指标用于比较相对优劣。

## 输出结论含义

- **概率最高方向**：市场最看好的赛果（如「客胜 50%」）。
- **体彩相对价值最高方向**：edge 最大者；若仍为负 EV，仅代表「相对最不差」，并非稳赚。

## 目录结构

```
football-odds-analysis/
├── main.py          # 直接运行入口（python main.py）
├── gui.py           # 足球弹窗入口（python gui.py）
├── nba_gui.py       # 篮球弹窗入口（python nba_gui.py，双击即可）
├── web_app.py       # 网页版服务（python web_app.py，浏览器中输入场次并查看分析）
├── src/
│   ├── config.py      # 常量与 URL 模板（含篮球）
│   ├── client.py      # HTTP 客户端（编码/Referer/重试）
│   ├── schedule.py    # 足球：解析竞彩赛事列表 + 周六015 映射
│   ├── odds.py        # 足球：解析百家欧指 game 数组
│   ├── analysis.py    # 足球：概率与价值分析 + 报告
│   ├── nba_schedule.py # 篮球：赛事列表 + 周六301/305 映射 + 按日期历史列表
│   ├── nba_odds.py    # 篮球：解析胜负 game 数组
│   ├── nba_analysis.py # 篮球：胜负概率与价值分析 + 报告
│   ├── nba_spread_odds.py  # 篮球：解析让分(亚洲盘) HTML 表格
│   ├── nba_spread_analysis.py # 篮球：让分方向共识概率与体彩价值 + 报告
│   ├── cli.py         # Typer 命令行
│   └── gui.py         # tkinter 弹窗（足球/篮球双模式，篮球含 胜负/让分/两者 切换）
├── tests/
│   └── test_analysis.py
├── pyproject.toml
└── README.md
```

## 反爬与合规提示

- 请求带浏览器 UA 与 Referer；数据 JS 需带欧指列表页 Referer 才能正常返回。
- 请控制请求频率，避免对数据源造成压力。数据版权归 titan007 / 球探体育所有。
