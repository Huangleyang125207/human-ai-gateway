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

# 2. 下所有 artifact (run 只一个,不必指 name)
echo "→ download to $TMP_DIR..."
gh run download "$RUN_ID" --dir "$TMP_DIR"

# artifact 内部布局随 CI 改过几版(扁平 / Gateway-mac-arm64-X.Y.Z 子目录 / 全路径嵌套)。
# 不猜布局:三件套各自 find 深挖出来,搬到 TMP_DIR 根。
for f in Gateway.app.tar.gz Gateway.app.tar.gz.sig latest.json; do
  HIT=$(find "$TMP_DIR" -type f -name "$f" | head -1)
  if [ -n "$HIT" ] && [ "$HIT" != "$TMP_DIR/$f" ]; then
    mv "$HIT" "$TMP_DIR/$f"
  fi
done

# 4. 检查关键文件齐
for f in Gateway.app.tar.gz Gateway.app.tar.gz.sig latest.json; do
  [ -f "$TMP_DIR/$f" ] || { echo "✗ missing: $f"; ls -la "$TMP_DIR"; exit 1; }
done
echo "→ 文件齐:"
ls -lh "$TMP_DIR" | grep -v "^total"

# 5. rsync 推 yanpai (deploy key sandbox 在 /opt/feedback-sink/data/updates/)
# 6.8 起 binary + sig 推 versioned 子目录 v${VERSION}/,manifest 还在根。
# CDN 用 versioned URL 永远不撞旧 cache(/updates/v0.1.26/Gateway.app.tar.gz 是新 key)。
# 旧 v0.1.x client(hardcoded 根路径 url) 不影响 — manifest 给的就是 versioned url。
VERSION=$(grep -oE '"version":\s*"[^"]+"' "$TMP_DIR/latest.json" | head -1 | sed -E 's/.*"([0-9.]+)".*/\1/')
[ -z "$VERSION" ] && { echo "✗ manifest 里抓不到 version"; exit 1; }
echo "→ version: $VERSION"
echo "→ rsync 推 yanpai versioned path + 根 manifest (国内→国内,几秒完)..."
rsync -e "ssh -i $DEPLOY_KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=no" \
      "$TMP_DIR/Gateway.app.tar.gz" \
      "$TMP_DIR/Gateway.app.tar.gz.sig" \
      "ubuntu@$YANPAI:v${VERSION}/"
rsync -e "ssh -i $DEPLOY_KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=no" \
      "$TMP_DIR/latest.json" \
      "ubuntu@$YANPAI:./"

# 6. verify
echo ""
echo "→ verify yanpai latest.json:"
curl -s --max-time 5 "http://$YANPAI:18080/updates/latest.json" | python3 -m json.tool 2>/dev/null | head -10

echo ""
echo "✓ sync 完成 — client 启动 5s 后自动 fetch + 下载"
