cd /home/user/sim_ds
# 校验文件齐备
for f in docs/CONTRACT.md docs/CONTRACT-tech-stack.md docs/CONTRACT-storage.md \
         docs/CONTRACT-scheduler.md docs/PLAN.md \
         agents/architect.md agents/scenario.md agents/sim-scheduler.md \
         agents/playback.md agents/frontend.md agents/evaluator.md \
         agents/scribe.md \
         migrations/001_init.sql migrations/002_metric_hierarchy.sql \
         migrations/003_partition_and_preagg.sql CHANGELOG.md; do
  test -f "$f" && echo "OK  $f" || echo "MISS $f"
done
# 迁移语法检查（PostgreSQL）
for m in migrations/*.sql; do psql -U postgres -v ON_ERROR_STOP=1 --single-transaction \
  -f "$m" postgres://localhost/sim_dev >/dev/null && echo "SQL OK $m"; done
