# 人情礼金记账系统 (Gift Bookkeeping App)

<p align="left">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue.svg" alt="Python Version">
  <img src="https://img.shields.io/badge/Flask-3.0.3-brightgreen.svg" alt="Flask Version">
  <img src="https://img.shields.io/badge/Database-SQLite%20%7C%20PostgreSQL-orange.svg" alt="Database">
  <img src="https://img.shields.io/badge/Frontend-Bootstrap%205%20%7C%20ECharts-purple.svg" alt="Frontend">
  <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License">
</p>

> **简洁、安全、全能的人情往来与礼金财务管理系统**。支持自然语言智能记账、专属宴席独立台账、人情往来精准对账、权威万年历与节假日调休感知、AI 记账助手、多渠道 Webhook 告警与 WebDAV 加密云备份。
>
> 📌 **当前版本**：`V10.11.27` | 📖 **[查看全量版本发布历史与更新日志 (docs/CHANGELOG.md)](docs/CHANGELOG.md)**

<!-- 
  【AI 协作与维护规范 - 严禁违背】
  本项目严格遵循文档分层治理架构（详见根目录 AGENTS.md）：
  1. 严禁在本 README.md 中追加版本更新公告、历史变更日志或长篇技术细节！README.md 必须严格保持在 150-180 行以内的极简自述形态。
  2. 新版本发布与全量更新日志：请一律追加至 docs/CHANGELOG.md。
  3. 架构设计与 ADR 决策记录：请一律追加至 docs/PSD_Design_Document.md 及 docs/PSD_Design_Document.html。
  4. 部署运维说明：请更新 docs/DEPLOYMENT.md；样例数据规范：请更新 docs/SAMPLE_DATA.md。
-->

---

## 🔑 默认管理员账号与安全凭证

初次部署启动后，系统将自动创建纯净数据库与初始管理员账号：
- **登录账号**：`admin`
- **初始密码**：`admin123`
- **安全建议**：生产环境部署时，建议通过环境变量设置自定义 `SECRET_KEY`，并在首次登录后立即进入安全中心修改管理员密码及密保问答。

---

## 🌟 核心功能特性

系统围绕中国传统人情往来与家庭财务场景深度设计，提供 9 大核心业务能力：

1. 📖 **智能礼金账本 (Gift Ledger)**
   - **自然语言复合语义记账**：直接粘贴长句（如“昨天李四儿子满月微信随了600；收张三结婚礼金888”），内置规则引擎自动提取姓名、金额、事由并批量拆解入库；
   - **大写金额与时间补录**：中文大写数字（壹仟/六百等）自动识别折算，支持自定义登记时间精准补录历史记录；
   - **多格式导入导出**：支持 CSV、Excel（`.xlsx`）模板化批量导入与结构化列映射，支持按条件筛选精准导出。

2. 🍷 **专属宴席台账 (Banquets)**
   - **办席专属大账本**：根据办席事由自动聚合收礼明细，独立统计宴席预算、实际开销与礼金收支；
   - **免登录专属分享**：生成随机安全 Token 外链，支持设置有效期与口令保护，便于宴席现场或亲友只读查看；
   - **双向数据同步**：支持随时从礼金主账本拉取增量记录，保证宴席明细账目一致。

3. ⚖️ **人情往来对账 (Reconciliation)**
   - **收送平衡大盘**：按亲友姓名全景聚合其所有收礼、送礼往来，直观展示【收礼总额】、【送礼总额】与【人情结余】；
   - **往来明细抽屉**：一键滑出该亲友全周期的每笔往来流水，智能标记顺差/逆差状态，人情收付一目了然。

4. 🎂 **亲友纪念日备忘 (Anniversary Reminders)**
   - **公农历双轨预警**：支持亲友生日、结婚纪念日、寿宴等重要节点备忘，公农历日期自动换算；
   - **定时多轮推送**：自定义提前预警天数（1~30天），后台异步线程定时巡检，支持多通道轮询调度推送。

5. 📅 **万年历与气象感知 (Perpetual Calendar & Weather)**
   - **本地权威万年历**：内置完整农历历法引擎（干支纪年、生肖、建除十二神吉相、节气）；
   - **法定节假日班休联动**：自动同步国家法定节假日放假与调休工作日数据，日历网格直观展示班/休徽章；
   - **实时天气与预报**：集成 Open-Meteo 免费气象接口，提供城市实时温湿度、空气质量与未来预报，支持多级缓存降级保障。

6. 📊 **数据看板与专业导出 (Dashboard & Export)**
   - **可视化分析看板**：集成 ECharts，提供月度/年度收支走势折线图、事由分布饼图与亲友往来 TOP10 排行；
   - **传统中式 A4 打印**：纯 CSS 实现古典竖排人情簿 A4 打印预览（含金额大写、页眉页脚与汇总栏）；
   - **专业对账单与海报**：服务端一键生成 PDF 对账单；前端支持渲染 375px 手机端暖色长图海报（含二维码水印）。

7. 👨‍👩‍👧‍👦 **家庭多成员协作 (Family Group)**
   - **多角色权限模型**：支持创建家庭组并邀请成员（家长 Head / 成员 Member / 只读 Viewer）；
   - **全家汇总与隔离**：家长可集中穿透查看全家总收支，普通成员专注维护个人账目，实现人情共享与隐私隔离统一。

8. 🤖 **AI 助手与生态互联 (AI & Webhooks)**
   - **AI 智能记账助手**：支持对接 OpenAI 兼容的大模型服务，内置联网搜索兜底，支持拍照识别礼金簿图片（OCR）；
   - **企业微信智能长连接**：基于官方 Python SDK（`wecom-aibot-python-sdk`）通过 WebSocket 直连企微服务器，群聊内 `@机器人` 自动捕获会话；
   - **多渠道 Webhook 矩阵**：支持钉钉、飞书、企业微信、Server酱、Bark 等全渠道事件触发推送。

9. 🔒 **安全架构与权限体系 (Security & Administration)**
   - **敏感凭据零明文落盘**：所有 Webhook 密钥、机器人 Secret、WebDAV 密码均通过 **AES-256-GCM** 对称加密入库；
   - **日志全自动递归脱敏**：系统审计日志与 Webhook 日志全面脱敏，敏感关键字自动替换为 `***MASKED***`；
   - **细粒度权限控制**：基于角色的菜单与按钮级鉴权，支持普通用户申请权限工单流转审批；
   - **WebDAV 云端备份与回收站**：定时自动生成加密 zip 备份并同步至坚果云等 WebDAV 存储；全系统统一软删除回收站。

---

## 🚀 快速启动

### 方式一：本地直接运行 (Windows / macOS / Linux)

```bash
# 1. 安装项目依赖
pip install -r requirements.txt

# 2. 启动应用 (默认监听 11443 端口)
python app.py
```
> 浏览器访问：`http://127.0.0.1:11443`

### 方式二：生产服务器一键运行 (推荐 Linux 云服务器)

系统根目录提供全自动运维脚本 `run.sh`（自动创建独立虚拟环境 `venv` + 增量安装依赖 + 自动生成 SSL 证书 + 后台守护）：

```bash
chmod +x run.sh
./run.sh start      # 启动服务
./run.sh status     # 查看运行状态与访问信息
./run.sh restart    # 重启服务
./run.sh stop       # 停止服务
```

---

## 📂 系统文件架构概览

```text
gift_bookkeeping_app/
├── app.py                     # [核心] Flask 主应用启动唯一入口
├── run.sh                     # [核心] Linux 一键后台运维与服务管理脚本
├── requirements.txt           # [核心] Python 依赖清单
├── .gitignore                 # [核心] Git 忽略规则
├── README.md                  # [精简自述] 项目说明、快速上手与架构导航
├── gift_bookkeeping.db        # [数据] 开箱即用官方样例数据库
│
├── docs/                      # 📂 [文档中心] 统一管理系统设计、运维手册与发布日志
│   ├── DEPLOYMENT.md          # 详细部署与 Nginx/SSL/Git 运维手册
│   ├── PSD_Design_Document.md # 详细设计与重构决策文档 (Markdown 原生版)
│   ├── PSD_Design_Document.html # 设计文档图表离线 HTML 交互版
│   ├── CHANGELOG.md           # 全量版本演进与历史变更日志 (V2 ~ V10.11.27)
│   ├── SAMPLE_DATA.md         # 样例数据体系与 9 项推送前核查规范
│   └── ANDROID_BUILD.md       # Android 原生 APK 打包指南
│
├── config/                    # 📂 [配置中心] 统一管理部署与服务配置
│   └── nginx_ssl.conf         # Nginx HTTPS SNI 多域名代理模板 (支持双路径回退)
│
├── bin/                       # 运维管理子脚本模块 (service, config, db_setup, etc.)
├── routes/                    # Flask 业务路由注册包 (routes_ext, routes_ai, etc.)
├── services/                  # 核心服务层与数据模型 (models, ai_service, etc.)
├── templates/                 # 前端 Jinja2 HTML 模板
├── static/                    # 前端静态静态资源 (CSS, JS, Fonts)
├── tools/                     # 工具脚本 (SSL 证书生成等)
├── aibot/                     # 企微 SDK 源码包
├── data/                      # 生产持久化运行库与附件 (仅本地, gitignore)
└── logs/                      # 运行日志/PID/备份/API缓存 (仅本地, gitignore)
```

---

## 📚 详细文档导航

深入了解系统部署、架构设计或二次开发，请参阅 `docs/` 目录下的专有手册：

- 🛠️ **[完整部署与运维手册 (docs/DEPLOYMENT.md)](docs/DEPLOYMENT.md)**：包含端口配置、多项目共用 443 SNI 分流、自签名 SSL 证书定制、Nginx 自动渲染以及 Linux 服务器代码免冲突更新方案；
- 📐 **[PSD 架构设计与重构决策文档 (docs/PSD_Design_Document.md)](docs/PSD_Design_Document.md)**：包含系统全景技术栈审计、漂移矩阵分析、前后台完整设计规格及 ADR-01~57 全部架构决策记录（另备有包含完整图表的 [HTML 交互版](docs/PSD_Design_Document.html)）；
- 📜 **[全量版本发布与变更日志 (docs/CHANGELOG.md)](docs/CHANGELOG.md)**：记录从 V2 至 V10.11.27 每一个版本的迭代日志与详细技术升级公告；
- 📦 **[开箱即用样例数据体系规范 (docs/SAMPLE_DATA.md)](docs/SAMPLE_DATA.md)**：包含 151 条高仿真演示记录构成、多角色测试账号矩阵、敏感数据脱敏准则及推送前 9 项核查红线；
- 📱 **[Android APK 打包指南 (docs/ANDROID_BUILD.md)](docs/ANDROID_BUILD.md)**：基于 GitHub Actions 与 Buildozer 的移动端离线安装包自动构建流程；
- 🌐 **[多形态交付生态矩阵 (Ecosystem)](docs/DEPLOYMENT.md#八项目多形态交付矩阵-ecosystem)**：了解 Web 原生版、Docker Compose 版与 Android APK 版的源码仓库。

---

## 📄 开源许可证

本项目基于 [MIT License](LICENSE) 开源许可协议发布。
