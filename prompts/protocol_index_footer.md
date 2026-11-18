
何时调 load_protocol:
· 要 patch_journal_block / insert_journal_block / 写 #commit 之前 → 先 load 'schedule'
· 普通聊天 / 拖图回复 / 简单 read_today_schedule → 不必 load
· vision 工作流 hint 在用户消息里 server 已注入,不必单独 load
