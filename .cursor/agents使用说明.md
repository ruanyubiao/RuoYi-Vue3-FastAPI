# Cursor Subagents 起步包（Python / C++ / Node.js / Vue 通用）

本包提供 4 个项目级 Subagent 配置，以及可直接复制到 Cursor Agent 输入框的中文自然语言提示词。

## 1. 安装

将压缩包中的 `.cursor/agents/` 目录复制到你的项目根目录，最后结构如下：

```text
your-project/
└── .cursor/
    └── agents/
        ├── code-explorer.md
        ├── test-designer.md
        ├── code-reviewer.md
        └── verifier.md
```

注意：Cursor 当前使用的项目级目录是 `.cursor/agents/`（复数 agents），不是 `.cursor/agent/`。

这些文件是自定义 Subagent，不是 Rules，也不是 Skills。它们使用 Cursor 支持的 Markdown + YAML frontmatter 格式。`readonly: true` 用于限制子 Agent 的文件修改和状态变更能力，但仍应检查它实际执行的命令和输出。

复制后，重新打开 Agent 面板或开始新的 Agent 对话；确认项目中的 `.cursor/agents/` 已被识别。可在提示词中用 `/code-explorer` 等方式尝试调用，也可以用自然语言要求主 Agent 委派。如果未识别，检查文件路径、frontmatter 和 Cursor 版本。


### 新聊天窗口主动确认
```text

请检查当前项目 `.cursor/agents/` 下的 Subagent 配置。

目标工作流：
- 主 Agent：需求分析、Plan 制定、方案决策、代码实施和结果汇总。
- code-explorer：只读探索代码、调用链、依赖和影响范围。
- test-designer：独立设计测试矩阵和验收标准。
- code-reviewer：只读审查实现 diff，发现有证据的缺陷。
- verifier：独立核验验收条件、运行测试并记录实际结果。

请遵循当前 Cursor 官方支持的 Subagent 文件格式。

检查每个文件的 YAML frontmatter、角色职责、只读边界和输出要求。确保角色之间职责清晰，避免重复工作。

同时检查 README 中的使用说明和自然语言提示词是否完整，覆盖 Plan 生成、实施、并行探索、独立评审和最终验证。

如果存在问题，只修改必要的配置文件，并说明修改原因。不要修改业务代码，不要执行 Git commit 或 push。

```

## 2. 推荐的角色分工

- **主 Agent（普通 Cursor Agent，不需要创建成 Subagent 文件）**：理解需求、调用子 Agent、决定技术方案、生成最终 Plan、实施代码、集成结果。
- **code-explorer**：只读调查现状、调用链、依赖、受影响文件和风险。
- **test-designer**：只读地独立设计测试矩阵和可验证的验收标准。
- **code-reviewer**：只读审查实现 diff，寻找有证据的缺陷。
- **verifier**：只读地运行或核验可运行的验证命令，记录实际结果。

推荐顺序：

1. 小任务：主 Agent 直接实现并验证，不必强行调用 Subagents。
2. 中大型任务：Plan 模式 → code-explorer + test-designer 调查 → 主 Agent 生成最终 Plan → 你审查 Plan → 主 Agent 实施。
3. 实施完成：code-reviewer 和 verifier 独立检查 → 主 Agent 修复 → 重新验证 → 你检查 diff 并决定 Git 提交。

不要让多个 Subagent 默认同时编辑同一工作区中的相同文件。当前配置中的子 Agent 都是只读角色，适合先做分析和验证。

## 3. 自然语言提示词：生成 Plan

在 Cursor 的 **Plan 模式**中粘贴：

> 请为当前需求制定实施计划，先不要修改代码。
>
> 1. 明确需求、目标、范围、约束和验收条件。
> 2. 使用 `code-explorer` 调查现有代码、调用链、关键文件、依赖关系和潜在影响。
> 3. 使用 `test-designer` 独立分析正常路径、异常路径、边界条件、回归风险和验收标准。
> 4. 主 Agent 综合结果，比较可行方案，选择推荐设计并说明取舍。
> 5. 生成 `implementation-plan.md`，包含：问题与目标、当前实现、推荐方案、实施步骤与依赖、修改文件范围、测试矩阵、验收标准、兼容性与风险、回滚考虑。
> 6. 区分已经由代码证据确认的事实与尚未验证的假设。
> 7. 检查计划是否存在遗漏、步骤依赖错误或无法客观验证的验收条件。
>
> 最后输出计划和需要我确认的问题，不要开始实施。如果当前环境无法调用指定 Subagent，请明确说明，不要声称已经调用。

**职责原则：** code-explorer 负责“摸清现状”，test-designer 负责“如何验证”，主 Agent 负责“决定怎么改并生成最终 Plan”。

## 4. 自然语言提示词：实施 Plan

确认计划后，在普通 Agent 模式粘贴：

> 按照已经确认的 `implementation-plan.md` 执行实施。
>
> - 开始前检查工作区状态，不要覆盖或撤销我的现有修改。
> - 按计划顺序执行；先处理依赖，再处理依赖它的步骤。
> - 遵守项目现有架构、编码规范和测试约定，不要无故引入新依赖。
> - 如果发现计划与实际代码不符、需要扩大修改范围或出现重大设计分歧，先暂停并说明原因，不要擅自改变目标。
> - 完成每个阶段后记录进度和验证结果；必要时更新计划并解释偏离原因。
> - 运行适当的测试、构建、lint 和类型检查，只报告实际执行过的结果。
> - 不要执行 git commit、push、reset 或其他未获明确授权的破坏性操作。
>
> 最终汇报：修改文件、关键设计、完成的计划步骤、实际运行的命令及结果、未完成项、风险和建议的下一步。

## 5. 自然语言提示词：并行代码探索和测试设计

> 先不要修改代码。请并行委派：
>
> - `code-explorer`：调查实现、调用链、依赖、受影响文件和兼容性约束。
> - `test-designer`：独立设计测试矩阵和验收标准。
>
> 等两个任务返回后，主 Agent 综合结论，指出事实、假设、风险和待确认问题。不要把未经验证的推测写成事实。

## 6. 自然语言提示词：实施后独立评审

> 请在当前实现完成后，独立委派 `code-reviewer` 和 `verifier` 分别执行：
>
> - `code-reviewer`：优先审查当前任务的 diff 和周边调用，报告有证据的真实缺陷，不修改文件。
> - `verifier`：根据验收标准识别并运行适当的验证命令，记录实际命令和结果，不修改文件。
>
> 两者分别报告，不要互相复制结论。主 Agent 汇总问题，按严重程度排序，标明确认的缺陷、未验证的风险和验证失败。不要自动提交 Git。

## 7. 自然语言提示词：让 Cursor 检查并完善配置

如果想让 Cursor 按当前版本核验这些文件，在 Agent 中粘贴：

> 请检查项目 `.cursor/agents/` 中的自定义 Subagent 配置是否符合当前 Cursor 官方支持的格式。
>
> - 检查 YAML frontmatter、name、description、model 和 readonly 字段。
> - 检查每个角色的职责是否有明显重叠。
> - 保持 code-explorer、test-designer、code-reviewer、verifier 的只读边界。
> - 不要自动添加危险命令、自动提交或自动推送。
> - 只修改确实有问题的配置，并说明修改原因。
> - 不要修改业务代码。

## 8. 使用建议与注意事项

- Subagent 有独立上下文，因此要明确传递需求、计划、目标分支和验收标准。
- 不要为简单的单文件改动强行并行化；启动多个 Agent 会增加延迟和模型用量。
- `readonly: true` 适合探索、设计、评审和验证角色。
- 评审 Agent 没发现问题不代表代码没有 Bug；测试必须以实际运行结果为准。
- 项目级配置适合提交到 Git，让团队共享；提交前检查提示词中是否包含内部路径、秘密或敏感信息。
- 主 Agent 是普通 Cursor Agent，不需要创建一个名为 `main-agent.md` 的子 Agent 来“替代”主 Agent。主 Agent 的行为主要由当前任务提示词、项目 Rules 和 Plan 模式决定。
