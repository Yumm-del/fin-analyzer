# Fin Analyzer 首轮评测

本轮面向 AI 产品运营与 Agent 效果运营岗位，先建立可复现的产品质量证据。
当前产品是单轮检索分析工作流，尚未具备多轮社交对话能力。

## 三种证据分别记录

1. 程序契约：提示词要求、来源说明、空响应及超时控制；不调用模型。
2. 真实模型：给定固定合成资料后调用现有 DeepSeek，保存原始响应；生成成功不等于正确。
3. 人工评审与真实试用：分别填写评分及观察记录；没有收集的反馈保持待完成。

数据集包含 8 个不同的合成场景，使用 example.invalid 来源，避免把测试内容误认为真实披露。
不记录用户密钥，也不把模拟 API 响应当作真实模型结果。

## 运行

在项目根目录、已安装原项目核心依赖的 Python 中执行：

```powershell
python -m evals.run --output evals/runs/current
python -m evals.run --revision bfe10ca --output evals/runs/baseline
python -m evals.run --live --limit 2 --output evals/runs/live
python -m evals.run --live --case-ids E03,E04,E05,E06,E07,E08 --output evals/runs/round2
```

最后一条会调用现有 DeepSeek 配置，可能产生费用。默认只跑两个场景，最多允许 8 个场景、3 次重复。
程序不会发起真实市场检索，行情接口也被固定输入替代，便于归因与重复比较。

不要把离线通过率、模型响应率或结构检查通过率写成“模型准确率”。

## 评分与复测

使用 [评审标准](rubric.md) 对真实模型报告逐条评分，附上对应语句及资料依据。
同一场景改动前后保持输入、模型和评分规则一致；模型多次输出不同属于需记录的波动。
新增问题记录见 [问题清单](issues.md)，用户试用流程见 [试用说明](trial.md)。

本轮未接入 DeepEval 或 Promptfoo 的运行时，也未复制它们的实现。
候选比较与调研记录见 [开源调研](research.md)。

## 指定场景与复现快照

--case-ids 优先于 --limit，未知、重复或空编号会直接报错。
每次真实请求保存 system/user 提示词，整批运行保存 source_snapshot.py 与 dataset_snapshot.json。
progress.json 会在每次请求完成后更新；没有完成的请求不写成成功。
source_sha256、dataset_sha256 和 runner_sha256 用于区分业务代码、数据集及检查器版本。
这些文件全部位于默认忽略的 runs 目录，不记录密钥。

## 评分来源

助手初评保存为 assistant_review，明确它不是独立人工标注。
真实用户与项目负责人填写的 human_review 保持独立；没有实际评审就仍为 pending。
