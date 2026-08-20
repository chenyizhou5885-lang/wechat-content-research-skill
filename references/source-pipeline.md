# 可审计信源流水线

研究时把宿主搜索、搜狗召回、WebBridge 核验和人工提供材料统一写入任务目录的 `raw_sources.json`。复制 `templates/raw_sources.json` 作为起点，不得只在报告中口头描述检索过程。

## 必填结构

- `research_brief`：主题、行业和实际时间范围。
- `requirements`：是否必须完成公众号调研，以及最低文章数和发布者数。
- `queries`：真实执行的查询词、渠道与用途。
- `tool_attempts`：工具调用、命令、状态、错误、自动恢复动作与时间。
- `candidate_pool`：发现的候选机构、页面或公众号；候选不等于正式来源。
- `enterprise_materials`：企业一手材料及公开/授权状态。
- `results`：实际打开并读取的页面或文章。
- `claim_ledger`：核心事实与引用来源的映射。
- `selected_topics`：推荐级别及其证据来源。

## `tool_attempts` 示例

```json
{
  "tool": "kimi-webbridge",
  "attempted": true,
  "status": "recovered",
  "command": "node scripts/search-wechat.js \"FDE 企业 AI\" -n 5 -r",
  "auto_start_attempted": true,
  "error": null,
  "timestamp": "2026-08-20T12:00:00Z"
}
```

只有真实执行后才能写 `attempted: true`。声称工具不可用时必须保存失败命令、错误和恢复结果。

## `results` 示例

```json
{
  "id": "src-openai-1",
  "title": "页面实际标题",
  "publisher": "OpenAI",
  "source_type": "company_official",
  "originality": "original",
  "published_at": "2026-08-01",
  "url": "https://搜索发现地址",
  "final_url": "https://openai.com/最终页面",
  "visited": true,
  "access": "open",
  "author": "OpenAI",
  "platform": "web",
  "verification": "verified",
  "content_evidence": ["页面中实际读取到、与本轮结论有关的具体信息"],
  "supports": ["claim-1"]
}
```

`source_type` 只使用：

- `government_official`
- `regulator_official`
- `association_official`
- `academic_primary`
- `research_report_primary`
- `company_official`
- `enterprise_internal`
- `media_original`
- `vertical_media_original`
- `expert_original`
- `competitor_official`
- `aggregator`
- `portal_self_media`
- `advertorial`
- `directory_or_review`
- `unknown`

`originality` 只使用 `original / reprint / summary / unknown`。转载页不得通过改写 `source_type` 冒充原始来源。

微信公众号文章额外填写：

```json
{
  "platform": "wechat",
  "verification": "verified",
  "verified_title": "浏览器读取标题",
  "verified_publisher": "浏览器读取公众号",
  "verified_published_at": "2026-08-01",
  "body_length": 2380
}
```

只有 WebBridge 校验标题、发布者、日期、正文和最终微信 URL 全部通过，`verification` 才能写 `verified`。

## `claim_ledger` 示例

```json
{
  "id": "claim-1",
  "claim": "某公司宣布成立新的部署组织",
  "claim_type": "company_action",
  "core": true,
  "source_ids": ["src-company-official", "src-independent-media"]
}
```

`claim_type` 使用 `number / forecast / company_action / quote / definition / policy / general`。除 `general` 外的核心事实必须由 S 级原始来源支撑；原始材料不可公开时，使用两个相互独立的 A 级原创来源。

## 执行命令

```bash
python3 scripts/build_sources.py --raw raw_sources.json --out sources.json
python3 scripts/validate_research.py --sources sources.json --mode writing --report research-report.md --article article-draft.md
```

第一条命令清洗来源、评级、审计核心事实和公众号覆盖；第二条命令是进入写作前的硬门禁。退出码非零时不得创建或交付文章成稿。
