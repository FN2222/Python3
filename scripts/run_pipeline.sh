#!/usr/bin/env bash
# NetworkLessons PDF -> 中文笔记 一键流水线(macOS / Linux / WSL)
#
#   ./scripts/run_pipeline.sh --install --source-root /mnt/d/NetworkLessons/All-Courses-v3.0
#   ./scripts/run_pipeline.sh --path OSPF --limit 3
#   ./scripts/run_pipeline.sh --build-only
#
# 参数: --install --build-only --skip-doctor --force
#       --source-root DIR  --notes-dir DIR  --build-dir DIR
#       --path KEYWORD     --limit N        --id PDF_ID
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

INSTALL=0
BUILD_ONLY=0
SKIP_DOCTOR=0
COMMON=()
SELECT=()

# 注:macOS 自带 bash 3.2,空数组展开必须写成 ${ARR[@]+"${ARR[@]}"},否则 set -u 会报错
while [[ $# -gt 0 ]]; do
  case "$1" in
    --install)      INSTALL=1; shift ;;
    --build-only)   BUILD_ONLY=1; shift ;;
    --skip-doctor)  SKIP_DOCTOR=1; shift ;;
    --source-root)  COMMON+=(--source-root "$2"); shift 2 ;;
    --notes-dir)    COMMON+=(--notes-dir "$2"); shift 2 ;;
    --build-dir)    COMMON+=(--build-dir "$2"); shift 2 ;;
    --path)         SELECT+=(--path "$2"); shift 2 ;;
    --limit)        SELECT+=(--limit "$2"); shift 2 ;;
    --id)           SELECT+=(--id "$2"); shift 2 ;;
    --force)        SELECT+=(--force); shift ;;
    -h|--help)      sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

PY="$REPO/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  if [[ $INSTALL -eq 1 ]]; then
    echo "==> 创建虚拟环境 .venv"
    python3 -m venv .venv
  else
    PY="$(command -v python3)"
  fi
fi

if [[ $INSTALL -eq 1 ]]; then
  echo "==> 安装依赖"
  "$PY" -m pip install --upgrade pip -q
  "$PY" -m pip install -r requirements.txt -q
fi

[[ -f config/pipeline.json ]] || "$PY" -m nlnotes init

if [[ $SKIP_DOCTOR -eq 0 ]]; then
  echo "==> 环境体检"
  "$PY" -m nlnotes doctor ${COMMON[@]+"${COMMON[@]}"} || \
    echo "警告: 体检发现问题(见上)。自制图的中文可能显示为方块。" >&2
fi

if [[ $BUILD_ONLY -eq 1 ]]; then
  echo "==> 校验 + 渲染 + 组装"
  set +e
  "$PY" -m nlnotes build ${COMMON[@]+"${COMMON[@]}"} ${SELECT[@]+"${SELECT[@]}"}
  RC=$?
  set -e
  "$PY" -m nlnotes status --detail ${COMMON[@]+"${COMMON[@]}"} || true
  if [[ $RC -ne 0 ]]; then
    echo "部分章节未通过门禁。报告: build/reports/<pdf_id>.json;修订规则: prompts/40-修订循环.md" >&2
  else
    echo "✅ 全部通过,笔记已生成在 notes/"
  fi
  exit $RC
fi

echo "==> 准备阶段: scan + extract + tasks"
"$PY" -m nlnotes prepare ${COMMON[@]+"${COMMON[@]}"} ${SELECT[@]+"${SELECT[@]}"}

# next 子命令没有 --force 参数,过滤掉
NEXT_SELECT=()
if [[ ${#SELECT[@]} -gt 0 ]]; then
  for arg in "${SELECT[@]}"; do
    [[ "$arg" == "--force" ]] || NEXT_SELECT+=("$arg")
  done
fi

echo
echo "===== 接下来让 AI 处理这些章节 ====="
"$PY" -m nlnotes next --count 5 ${COMMON[@]+"${COMMON[@]}"} ${NEXT_SELECT[@]+"${NEXT_SELECT[@]}"} || true

cat <<'EOF'

下一步(把下面这段话交给 AI):

  读 build/tasks/<id>/TASK.md 并严格按它的要求产出 build/tasks/<id>/OUTPUT/note.json。
  figures.md 里的每张图都要打开看,把图上的文字登记到 labels_seen。
  写完运行  python -m nlnotes build --id <id>  ,按 build/reports/<id>.json 的报告
  逐条修到通过为止。不要修改门禁配置。

同时把 prompts/00-system-中文笔记作者.md 设为 AI 的系统提示词。
AI 写完后运行:  ./scripts/run_pipeline.sh --build-only
EOF
