# Third-party notices

This skill's natural-Chinese revision workflow was independently adapted with reference to the following MIT-licensed projects. No author voice profiles or repository-specific corpora are bundled.

## humanizer-zh

- Project: https://github.com/ai-zixun/humanizer-zh
- License: MIT
- Ideas referenced: Chinese translation-tone cleanup, mechanical contrast detection, document-level revision, and style-reference boundaries.

## humanize-writing

- Project: https://github.com/Lanqingsong/humanize-writing
- License: MIT
- Ideas referenced: stance-first drafting, information/structure/sentence/rhythm review layers, evidence preservation, and avoidance of detector-bypass claims.

The five mandatory Chinese writing rules and the concrete before/after example in `references/natural-writing.md` were supplied by the WorkBuddy skill owner for this project.

## wechat-article-search

- Project: https://github.com/zjp1997720/zhijian-skills/tree/main/skills/wechat-article-search
- Source revision: b2c82a6b3d73385d3a31f78d288d96445990b88c
- License: MIT; see `licenses/wechat-article-search-MIT.txt`
- Bundled component: the Sogou WeChat search script and its runtime dependency, built as `scripts/wechat-search.bundle.cjs`.
- Local adaptation: `scripts/search-wechat.js` enforces a default 365-day window and emits normalized JSON metadata.
