# AI 比价机器人助手

一个 Docker 一键部署的 AI 助手：接入 **企业微信 / 钉钉 / QQ 官方机器人**，
在任何聊天窗口里说「我想看流浪地球3」或「帮我查 AirPods Pro 的价格」，
机器人会跨 **美团 / 淘宝 / 京东 / 抖音** 各平台查询报价并推荐最低价。

```
企业微信(自建应用回调) ─┐
钉钉(Stream长连接)     ─┼→ PlatformAdapter → 统一消息 → Dispatcher
QQ官方机器人(WebSocket)─┘                                ↓
                        LLM(OpenAI兼容·DeepSeek等, function calling)
                                                    ↓ tool_call
                        compare_prices → PriceProvider 插件（当前为模拟源）
```

## 快速开始（零配置体验）

```bash
cp .env.example .env
python -m pip install -r requirements.txt
python -m app.cli        # 终端对话：说「我想看流浪地球3」
```

未配置 LLM Key 时自动进入规则模式（正则识别比价意图）；
配置 `LLM_API_KEY` 后即是完整 AI 对话。

## Docker 部署

**方式一：直接拉取镜像（推荐，无需克隆源码）**

```bash
mkdir price-bot && cd price-bot
curl -O https://raw.githubusercontent.com/DaisyYijin/ai-price-bot/master/docker-compose.yml
# 编辑 docker-compose.yml，把 ADMIN_USERNAME / ADMIN_PASSWORD 改成你的账号密码
mkdir -p config data logs
docker compose up -d        # 首次自动拉取镜像；更新: docker compose pull && docker compose up -d
```

**方式二：从源码构建**（本地开发或自定义修改后）

```bash
git clone https://github.com/DaisyYijin/ai-price-bot.git && cd ai-price-bot
mkdir -p config data logs
# 编辑 docker-compose.yml：注释 image 行、放开 build 行，再执行
docker compose up -d --build
```

打开 `http://服务器IP:2048/admin`，用 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 里设置的
账号密码直接登录（免首次注册），在网页里填写各平台密钥 →
保存（大模型/比价设置立即生效；平台接入点「立即重启」，容器自动拉起）。
镜像由 GitHub Actions 自动构建发布（`ghcr.io/daisyyijin/ai-price-bot`），支持 amd64/arm64。

- **钉钉 / QQ**：出站 WebSocket 长连接，部署在任何内网服务器即可，无需公网 IP。
- **企业微信**：需要公网可达的回调地址，本地调试可用 frp / 云函数 / 服务器反代，
  回调 URL 填 `http(s)://你的域名:2048/webhook/wecom`。
- 已有 `.env` 的老用户可直接 `cp .env config/config.env`，或把值填进网页后台（一次即可）。

### 持久化目录（三条独立映射）

| 宿主机目录 | 容器路径 | 内容 |
| --- | --- | --- |
| `./config` | `/app/config` | `config.env`：网页后台写入的配置（各平台密钥、开关、价格源） |
| `./data` | `/app/data` | `admin_password` 管理密码哈希、`session.key` 会话签名密钥 |
| `./logs` | `/app/logs` | `app.log` 应用日志（按天轮转保留 14 天；访问日志看 `docker logs`） |

### 网页管理后台（`/admin`）

| 能力 | 说明 |
| --- | --- |
| 配置填写 | 大模型 / 企业微信 / 钉钉 / QQ / 比价设置，全部网页表单填写，密钥不回传浏览器（留空即保持不变）；每个平台卡片顶部有注册与取值的步骤指引 |
| 模型选择 | 大模型区内置常用厂商预设（DeepSeek/智谱/Kimi/通义/OpenAI/Ollama），填好地址与 Key 后点「获取模型」在线拉取列表点选，不必手查模型名 |
| 连通性测试 | 每个平台一键测试：LLM 发一条真实补全、企微/钉钉/QQ 拉一次 access_token，当场验证密钥是否有效 |
| 热生效 | 保存后大模型与价格源立即生效；平台配置变更会提示「立即重启」 |
| 访问保护 | 账号密码由环境变量 `ADMIN_USERNAME`（默认 admin）/ `ADMIN_PASSWORD` 分别指定（改后 `docker compose up -d` 生效）；未设置密码时退回首次访问网页设置账号密码的流程（密码 PBKDF2 哈希落盘 `data/`）。Cookie 会话签名 7 天有效，连续 5 次失败锁定 60 秒 |

> 安全提示：管理后台与机器人服务共用 2048 端口。若服务器暴露公网，建议用防火墙/安全组
> 限制 `/admin` 的来源，或置于反向代理之后再加一层认证。

## 各平台接入指引

| 平台 | 入口 | 需要的配置 | 触发方式 |
| --- | --- | --- | --- |
| 企业微信 | [work.weixin.qq.com](https://work.weixin.qq.com) → 应用管理 → 创建自建应用 | `WECOM_CORP_ID` `WECOM_AGENT_ID` `WECOM_SECRET`，接收消息页设置 `WECOM_TOKEN` / `WECOM_ENCODING_AES_KEY` | 应用会话直接发消息 |
| 钉钉 | [open-dev.dingtalk.com](https://open-dev.dingtalk.com) → 应用开发 → 添加「机器人」能力，开启 **Stream 模式** | `DINGTALK_CLIENT_ID` `DINGTALK_CLIENT_SECRET` | 群内 @机器人 |
| QQ | [q.qq.com](https://q.qq.com) 创建机器人（个人开发者可注册） | `QQ_APP_ID` `QQ_CLIENT_SECRET` | 群内 @机器人 / 私聊 |
| LLM | [platform.deepseek.com](https://platform.deepseek.com)（或任意 OpenAI 兼容服务） | `LLM_BASE_URL` `LLM_API_KEY` `LLM_MODEL` | — |

在 `.env` 里把对应平台 `XXX_ENABLED=true` 并填好密钥，重启容器即可（或全程在
`/admin` 网页后台完成）。未启用的平台不加载，启动失败的平台会跳过并记日志，不影响其他平台。

## 换大模型

客户端为 OpenAI 兼容格式，换厂商只改三行：

```ini
# 智谱 GLM
LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
LLM_MODEL=glm-4.7
# Kimi:  https://api.moonshot.cn/v1  (moonshot-v1-32k)
# Ollama: http://你的机器:11434/v1   (qwen2.5:14b)
```

## 关于比价数据的诚实说明

**美团 / 淘宝 / 京东 / 抖音都没有公开的报价查询 API**（电影票尤其如此）。
当前版本使用内置**模拟数据源**跑通全流程：价格由 关键词+平台 哈希确定性生成，
同一关键词永远得到同一组报价，便于演示与测试，回复中会明确标注「模拟数据」。

数据源是插件化的（`app/providers/`）。接入真实数据时新建一个文件即可，核心代码零改动：

```python
# app/providers/jd_union.py —— 京东联盟示例
from app.core.models import Quote
from app.providers.base import PriceProvider, register

@register
class JdUnion(PriceProvider):
    name = "jd_union"
    platform = "京东"

    async def search(self, keyword: str, category: str = "综合") -> list[Quote]:
        ...  # 调用联盟 API，映射为 Quote 列表
```

然后在 `.env` 里 `PRICE_PROVIDERS=meituan,taobao,jd_union,douyin` 并在
`app/providers/__init__.py` 追加导入。可选的真实数据路径：

- **京东联盟**（union.jd.com，官方 CPS 接口，个人可注册）
- **大淘客 / 折淘客**（淘宝商品搜索）
- **抖音精选联盟**（巨量百应）

## 项目结构

```
app/
├── main.py            # FastAPI 装配：按开关加载平台适配器
├── cli.py             # 终端体验模式
├── config.py          # .env 配置
├── core/              # 统一消息模型 / 调度器（LLM工具循环）/ 会话历史
├── llm/               # OpenAI 兼容客户端 + 系统提示词
├── tools/             # compare_prices 工具（供 function calling）
├── providers/         # 价格数据源插件（内置四平台模拟源）
└── platforms/         # 企业微信 / 钉钉 / QQ 官方适配器
tests/                 # pytest：加解密往返、模拟源确定性、调度器工具循环
```

## 开发

```bash
python -m pytest               # 运行测试
python -m uvicorn app.main:app --reload   # 本地起服务
```
