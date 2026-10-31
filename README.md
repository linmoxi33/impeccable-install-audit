# impeccable-install-audit

离线核对 Impeccable 在多个 agent harness 里的安装副本是否一致——版本、引擎 pin、sha256、hook 目标，一次扫完。

**为什么现在需要它**：Impeccable 支持 20 多种 harness（Claude Code、Codex、Cursor、Copilot、Grok、Gemini、OpenCode、Pi…），安装器会把同一套 skill 分别写进各自的目录，甚至为每个目录复制一份 16 MB 引擎。只要装过两次、换过一次 harness、或从全局装到项目里，副本就会分叉；而上游唯一的自检 `impeccable check` 只比对远端版本号，在全新安装后仍会误报「Updates available」（[#1247](https://github.com/pbakaus/impeccable/issues/1247)），也不看本地完整性。

Upstream: https://github.com/pbakaus/impeccable

## 上游是什么，它缺什么

Impeccable 是一套「设计词汇」skill + 一个 Rust 引擎，通过 `/impeccable critique` 等 24 个命令给 coding agent 提供设计审查。安装后，每个 harness 目录下都有一份 `skills/impeccable/`：`SKILL.md`（skill 版本）、`scripts/VERSION`（引擎版本）、`scripts/engine-checksums.txt`（官方 sha256 pin）、`scripts/bin/<platform>/impeccable`（引擎二进制）。

上游自己记录了三类真实问题，且都没有本地检测手段：

- 版本分叉：ChatGPT 插件停在 v4.3.1，仓库已是 v4.5.2，「没有用户可见的更新路径」（[#1023](https://github.com/pbakaus/impeccable/issues/1023)，同问题此前在 #274 报过一次）。
- 重复引擎：安装器「往每个 harness 的 skill 目录写一份完整拷贝……一台机器上有三份相同副本（约 49 MB）」，且「很容易误提交 16 MB 的平台二进制」（[#1175](https://github.com/pbakaus/impeccable/issues/1175)）。
- hook 写错 scope：选择全局安装后，Codex/Grok 的 hook 仍写进当前项目，「这个项目现在有了第二份拷贝」（[#1190](https://github.com/pbakaus/impeccable/issues/1190)），而 hook 指向的 launcher 路径可能根本不存在。

这些都不是「再加一个功能」，而是**安装态不可验证**：没有任何命令能回答「我这台机器上的 5 份副本，是不是同一版本、同一个引擎、指向存在的文件」。

## 这个工具做什么

扫描一个目录树，找出所有 `<harness>/skills/impeccable` 安装，然后离线判定：

| 规则 | 判定 |
| --- | --- |
| `version-drift` | 同一根目录下多个 harness 的 `SKILL.md` 版本不一致 |
| `engine-pin-mismatch` | `scripts/VERSION` 与 `engine-checksums.txt` 里的版本不一致，或各副本引擎版本不一致 |
| `checksum-mismatch` | 引擎二进制实际 sha256 与 pin 的摘要不一致 |
| `duplicate-engine` | 同一引擎二进制被复制进多个 harness 目录（默认 ≥ 1 MiB 才计入） |
| `missing-engine` | 有 launcher 但目录内无二进制、共享缓存也没有（源码 checkout 降级为 warning） |
| `hook-target-missing` | `.codex`/`.grok`/`.github`/`.cursor`/`.claude` 的 hook manifest 指向的 launcher 不存在 |
| `version-unreadable` | `SKILL.md` 没有可解析的 frontmatter `version` |

**不做**：不下载、不校验远端发布、不安装/修复任何东西、不运行上游引擎、不联网。它只读本地文件，给出可断言的结论。

## 安装与用法

无第三方依赖，Python 3.8+，单文件：

```bash
# 1) 先跑自带的坏样例（3 个 harness，4 个 error，退出码 1）
python3 bin/impeccable-install-audit examples/in --min-engine-bytes 32

# 2) 再扫你自己的项目或全局安装
python3 bin/impeccable-install-audit . --json
python3 bin/impeccable-install-audit ~ --json
```

人类可读输出：

```text
$ python3 bin/impeccable-install-audit examples/in --min-engine-bytes 32
install  .agents      skill=4.7.0    engine=0.1.18   examples/in/.agents/skills/impeccable
install  .claude      skill=4.8.0    engine=0.1.18   examples/in/.claude/skills/impeccable
install  .grok        skill=4.8.0    engine=0.1.18   examples/in/.grok/skills/impeccable
ERROR   version-drift        skill 版本跨 harness 不一致: .agents=4.7.0, .claude=4.8.0, .grok=4.8.0
ERROR   checksum-mismatch    sha256=db80460285257099… 与 pin 的 3b7ce0cb47bf04e5… 不一致
ERROR   duplicate-engine     同一引擎二进制(108 B, sha256=3b7ce0cb47bf04e5…)被复制了 2 份: …
ERROR   hook-target-missing  hook 指向的 launcher 不存在: ~/.agents/skills/impeccable/scripts/impeccable

3 install(s), 4 error(s), 0 warning(s)
```

`--json` 输出（完整样例见 [`examples/out/report.json`](examples/out/report.json)）：

```json
{
  "schema": "impeccable-install-audit/1",
  "ok": false,
  "summary": {"installs": 3, "findings": 4, "errors": 4, "warnings": 0, "roots": ["examples/in"]},
  "installs": [{"harness": ".agents", "path": "…", "skill_version": "4.7.0",
                "engine_version": "0.1.18", "launcher": true,
                "checksum_versions": ["0.1.18"], "binaries": []}],
  "findings": [{"rule": "version-drift", "severity": "error", "path": "examples/in",
                "message": "skill 版本跨 harness 不一致: …"}]
}
```

退出码：

| 码 | 含义 |
| --- | --- |
| 0 | 无 error（warning 允许） |
| 1 | 检出至少一个 error |
| 2 | 用法或输入错误（目录不存在 / 没找到任何安装） |

跑测试：`python3 -m unittest discover -s tests -v`（14 个用例）。

## 真实数据

在上游仓库自己的 checkout 上跑（`git clone --depth=1 --filter=blob:none --sparse`，含 `.claude` 与 `.agents` 两份安装）：

```text
$ python3 bin/impeccable-install-audit /tmp/up/impeccable
install  .agents  skill=4.8.0  engine=0.1.18  .agents/skills/impeccable
install  .claude  skill=4.8.0  engine=0.1.18  .claude/skills/impeccable
WARNING missing-engine  源码 checkout 不含引擎二进制（安装后才写入），跳过判定
WARNING missing-engine  源码 checkout 不含引擎二进制（安装后才写入），跳过判定

2 install(s), 0 error(s), 2 warning(s)
```

结论：仓库内的两份副本版本与引擎 pin 一致（0 error）；二进制被 `.gitignore` 排除，所以源码 checkout 只报 warning——这条降级规则就是被这次真实运行逼出来的，否则会误伤所有从源码构建的人。

## 局限

- 只认 `<harness>/skills/impeccable` 这一种布局；上游若改目录结构，需要同步更新 `HOOK_MANIFESTS` 与发现逻辑。
- 二进制校验依赖 `engine-checksums.txt` 同时存在于该副本内；缺这个文件时只做版本一致性检查，不猜摘要。
- 不校验远端发布、不校验签名（`docs/BUNDLE-SIGNING.md` 的签名链不在范围内）。
- 不修改任何文件；修复仍需 `impeccable update` / 手动删除重复副本。
- `~/.impeccable/bin/` 共享缓存只做「是否存在」判断，不校验缓存内二进制的摘要。

## 与同类项目的差异

`gh search repos "agent skill install audit"` 无命中；`gh search repos "impeccable"` 只命中上游本身与几个 skill 精简版/适配版（`impeccable-lite` 27★、`pi-impeccable` 17★），都不做安装态审计；`gh search code "engine-checksums.txt"` 的命中全部在上游仓库内部。上游自带 `impeccable check` 只比对远端版本号、会误报（#1247），且不读 `engine-checksums.txt`、不看 hook manifest。本工具是唯一一个把「跨 harness 一致性 + 引擎 pin + sha256 + hook 目标」放在一次离线扫描里给出退出码的实现。

## 本轮创新

把「agent skill 到底装没装对」从一次联网版本查询，变成一次可断言的本地一致性审计：首次把 `engine-checksums.txt` 的 sha256 pin、跨 harness 副本版本、hook manifest 目标三者合并成同一份报告，并用真实仓库 checkout 跑出了「副本一致、二进制不入库」这一可复现结论（上游 #1175/#1190/#1023 都只描述了症状，没有检测器）。

## License

MIT
