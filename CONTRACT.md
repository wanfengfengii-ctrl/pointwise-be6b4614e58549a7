# 整数标识关联审查约定

## 观察入口

probe.py 是观察器，不含期望匹配算法。所有关联都由原版 DataFrame.merge 执行。
通过 python3 bootstrap.py probe.py normal 或 incident 读取内置样例；
python3 bootstrap.py probe.py --spec case.json 读取自定义输入。
Python 调用入口为 probe.run_case(spec)，返回可 JSON 序列化的观察对象。

输入对象的完整样例：
{"left":{"dtype":"int64","rows":[["L1",1],["L2",2],["L3",3]]},"right":{"dtype":"uint64","rows":[["R3",3],["R2",2],["R4",4]]},"how":"left","partition":false,"validate":"one_to_one"}

left/right 各含 dtype 和 rows；dtype 只取 int64、uint64、Int64、UInt64，
rows 每项为 [稳定行ID,键]。ID 是非空字符串，同侧唯一，不随重排重新编号。
键是其声明类型范围内的 JSON 整数，只有 Int64/UInt64 可用 null。
有符号范围为 -9223372036854775808 至 9223372036854775807；
无符号范围为 0 至 18446744073709551615。允许空表。
how 只取 inner/left；partition 是布尔值；validate 只取 null 或 one_to_one。
输入字段均必填，不接收其他字段；输入非法时抛 ValueError，不作为关联失败证据。
sort=False 固定。partition=true 时两表增加 int64 的 part=7，关联键为 key、part；
false 时只使用 key。其他列不参与关联；不扩展索引关联、浮点键或其他关联方式。

返回字段：
- spec：输入的副本。
- versions：pandas、numpy 版本。
- inputs：两侧建表后实际 key 的 dtype 与按源顺序保存的 keys。
- rows：输出顺序的记录，含 left_id、right_id、key，启用分区时另含 part。
- dtypes：输出全部列的 dtype 字符串。
- warnings：调用期间每条警告的 type、message。
- error：成功为 null，关联抛异常时为 type、message；该情况 rows、dtypes 为空。

NumPy 标量转为对应 Python 标量；缺失值转为 JSON null。
逐列读取结果，不能用跨列数组转换改变整数精度。观察入口退出 0 表示取得观察，
不表示业务正确；只有合法输入的 merge 异常会记录到 error。
比较行身份和重复次数时忽略结果行序，不能仅比较行数、键列外观或 dtype。

## 业务口径与既有回归

业务标识按精确整数比较，不能先转浮点。两个非空键数值相等才匹配；
两边的空键相互匹配，这是本题沿用的 pandas 规则，不能按 SQL NULL 规则拒绝。
重复键保留所有左右行ID组合。inner 只输出匹配组合；left 还为每条无匹配左行
输出一次 right_id=null，并保留该左行的键。固定分区键不改变以上结果。
one_to_one 按原始精确键检查每侧唯一性，包含空键；真实重复应拒绝。
null 表示不要求唯一，不能把合法重复作为错误。

normal 样例的 (left_id,right_id,key) 多重集为
[["L1",null,1],["L2","R2",2],["L3","R3",3]]。
duplicates 样例保留 [["L0","R0",7],["L1","R0",7]]；
改用 one_to_one 须报 MergeError。
nullable 样例保留 [["LN","RN",null],["L1","R1",1]]。
python3 bootstrap.py checks.py normal 核对上述结果和源码完整性，成功标记为 NORMAL_REGRESSION_OK。

incident 的两侧键均唯一，业务应恰有
[["L0","R0",9007199254740992],["L1","R1",9007199254740993]]。
python3 bootstrap.py checks.py incident 按此作断言，原版稳定失败并含
MERGE_IDENTITY_MISMATCH。保留此命令及断言；审查完成不要求它变为通过。
这只是公开事故，不替代其他边界的审查。

## 审查产物与重放

REVIEW.md 引用原始模块及源码行号，追踪键处理、实际匹配及唯一性检查的联系，
写明实质根因、触发边界、发布意见和最小兼容修复建议。
docs/integer-merge.md 修订后应将现状、可用规避和库内建议分清，
说明各自适用范围，不能把建议写成当前版本已有保证。
调用方规避和库内建议都只需说明与伪代码，不修改生产实现。
独立期望只按输入、Python 精确整数和上述空值规则计算，
不得调用 pandas/NumPy 的关联、类型协调、因子化或采信原实现结果。
证据保留输入、完整观察、独立期望、差异和报告定位；结果格式其余部分自行组织。

review_evidence.py run 生成 evidence.json；
review_evidence.py verify 重新调用原观察入口、核对保存结果和报告引用，并执行原正常回归。
确认缺陷的案例应核对差异仍可复现，而不是要求原实现给出正确结果。
review_evidence.py demo 展示真实正常结果及身份误配，不能只打印成功标记。
三个入口均用 python3 bootstrap.py review_evidence.py COMMAND 执行。

重排、固定分区键、可空表示用单因素对照解释，兼顾组合中的变化；
大整数、缺失、真重复及安全整数范围正例以题面范围为准，不要求穷举所有输入。
审查只覆盖关联身份这一主轴，不增加性能、依赖升级、并发或恢复系统。
运行清单已提供 .pointwise-runtime.json，version=1，kind=cli；
setup 是 argv 数组的列表，verify/demo 各为 argv 数组。
交付时 setup 保持环境准备，verify/demo 分别改指向上述 verify/demo 入口。
