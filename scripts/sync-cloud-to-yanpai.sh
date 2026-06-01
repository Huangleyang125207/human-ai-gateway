#!/bin/bash
# sync-cloud-to-yanpai.sh — GitHub Actions artifact → 本机 → yanpai 中转
#
# 6.1 启用:之前 GitHub Actions 直接 rsync 推 yanpai,国际反向带宽 18-25KB/s,
# 150MB tar.gz 推 80min+ timeout。架构换成:Actions 只 upload artifact,
# 本机当 trust 出口下来 + 推国内 yanpai (秒级)。
#
# 用法:
#   bash sync-cloud-to-yanpai.sh                    # 拉最新 successful run
#   bash sync-cloud-to-yanpai.sh <run-id>           # 指定 run
#
# 依赖:
#   - gh CLI (auth ok)
#   - ~/.ssh/gateway-updates-deploy (rrsync sandbox 私钥)
#   - Clash 通(gh download 走 GitHub API)

set -e
cd "$(dirname "$0")/.."

YANPAI=101.42.108.30
DEPLOY_KEY=$HOME/.ssh/gateway-updates-deploy
WORKFLOW=build-mac.yml
TMP_DIR=$(mktemp -d -t gateway-sync.XXXX)
trap "rm -rf $TMP_DIR" EXIT

# 1. 拿 run id (param 或最新 success)
RUN_ID=${1:-}
if [ -z "$RUN_ID" ]; then
  echo "→ 找最新 successful run of $WORKFLOW..."
  RUN_ID=$(gh run list --workflow=$WORKFLOW --status=success --limit=1 --json databaseId --jq '.[0].databaseId')
  [ -z "$RUN_ID" ] && { echo "✗ 没找到 success run"; exit 1; }
fi
echo "→ 用 run id: $RUN_ID"

# 2. 拿这个 run 的 artifact name (含 version)
ART_NAME=$(gh run view "$RUN_ID" --json artifacts --jq '.artifacts[0].name')
[ -z "$ART_NAME" ] && { echo "✗ run $RUN_ID 没 artifact"; exit 1; }
echo "→ artifact: $ART_NAME"

# 3. 下到本地 tmp
echo "→ download to $TMP_DIR..."
gh run download "$RUN_ID" --name "$ART_NAME" --dir "$TMP_DIR"

# 4. 检查关键文件齐
for f in Gateway.app.tar.gz Gateway.app.tar.gz.sig latest.json; do
  [ -f "$TMP_DIR/$f" ] || { echo "✗ missing: $f"; ls -la "$TMP_DIR"; exit 1; }
done
echo "→ 文件齐:"
ls -lh "$TMP_DIR" | grep -v "^total"

# 5. rsync 推 yanpai (deploy key sandbox 在 /opt/feedback-sink/data/updates/)
echo "→ rsync 推 yanpai (国内→国内,几秒完)..."
rsync -e "ssh -i $DEPLOY_KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=no" \
      "$TMP_DIR/Gateway.app.tar.gz" \
      "$TMP_DIR/Gateway.app.tar.gz.sig" \
      "$TMP_DIR/latest.json" \
      ubuntu@$YANPAI:./

# 6. verify
echo ""
echo "→ verify yanpai latest.json:"
curl -s --max-time 5 "http://$YANPAI:18080/updates/latest.json" | python3 -m json.tool 2>/dev/null | head -10

echo ""
echo "✓ sync 完成 — client 启动 5s 后自动 fetch + 下载"
