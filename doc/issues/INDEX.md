# RMR 已解决异常归档

RMR 已解决异常的索引。正文不是 skill，每篇正文位于 `doc/issues/rmr-issue-<name>.md`，包含症状 / 根因 / 诊断 / 修复 / 验证 / 回滚 / 关联 / 触发关键词。处理异常时先按下方症状或报错原文检索对应文件，再 `Read` 该文件。

**异常一律只落文档、不做 skill**：skill 的 `description` 每请求全量加载，只增固定开销；触发词也只在本文件维护。

共 1 篇。

| 归档文档 | 症状 / 触发关键词 |
|---|---|
| [rmr-issue-language-list-empty.md](rmr-issue-language-list-empty.md) | 已修复：ESC → Language 标签列表为空；`AttributeError: 'list' object has no attribute 'languageID'`；GetLanguages 返回 list 而非 Rowset；SetLanguageID 不改 session；语言名乱码 |
