#!/usr/bin/env bash
# 把 dist/ 发布到 GitHub Pages（gh-pages 分支）。
#
# 用法（在 NAS 或本机项目根执行）：
#   ./scripts/deploy_pages.sh
#
# 环境变量：
#   TIDEWATCH_REMOTE  默认 git@github.com:nomiga-ww/tidewatch.git
#
# 说明：
#   - 用独立的临时 git 仓库推 gh-pages，避免污染主分支历史
#   - 推送前做页面数守门（宁可停更，不可发布半成品）
#   - SSH key 决定账号：默认 git@github.com 走 id_ed25519 -> nomiga-ww
set -euo pipefail

cd "$(dirname "$0")/.."
REMOTE="${TIDEWATCH_REMOTE:-git@github.com:nomiga-ww/tidewatch.git}"
MIN_PAGES="${TIDEWATCH_MIN_PAGES:-6}"

[ -d dist ] || { echo "❌ dist/ 不存在，请先执行 render --publish"; exit 1; }

PAGES=$(find dist -name '*.html' | wc -l | tr -d ' ')
if [ "$PAGES" -lt "$MIN_PAGES" ]; then
  echo "❌ 页面数 $PAGES < $MIN_PAGES，拒绝发布（保留上一版）"
  exit 1
fi

# 报告摘要里也应包含快照日期，便于追溯
SNAPSHOT=$(grep -rhoE "快照交易日: [0-9-]+" dist/*.html 2>/dev/null | head -1 | awk '{print $2}' || echo "unknown")

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cp -r dist/. "$TMP/"

# GitHub Pages 需要 .nojekyll（否则下划线开头文件被忽略）
touch "$TMP/.nojekyll"

cd "$TMP"
git init -q
git checkout -q -b gh-pages
git add -A
git -c user.name="tidewatch" \
    -c user.email="52682328+nomiga-ww@users.noreply.github.com" \
    commit -q -m "publish: snapshot ${SNAPSHOT} (${PAGES} pages)"
git push -f "$REMOTE" gh-pages

echo "✅ 已发布 ${PAGES} 页（快照 ${SNAPSHOT}）到 $REMOTE : gh-pages"
